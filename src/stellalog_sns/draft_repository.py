"""投稿前の編集内容を、投稿履歴とは別に保存する。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .models import Article, ContentBlock, PostSet
from .settings import default_app_data_dir


@dataclass(frozen=True, slots=True)
class Draft:
    id: str
    post: PostSet
    narration_script: str
    narration_manually_edited: bool
    updated_at: datetime


class DraftRepository:
    def __init__(self, app_dir: Path | str | None = None) -> None:
        self.path = (Path(app_dir) if app_dir is not None else default_app_data_dir()) / "drafts.sqlite3"
        self.warnings: list[str] = []

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS drafts ("
                    "id TEXT PRIMARY KEY, article_key TEXT NOT NULL, payload TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)"
                )
                yield connection
        finally:
            connection.close()

    @staticmethod
    def draft_id(post: PostSet) -> str:
        return hashlib.sha256(
            f"{post.article.article_key}|{post.selected_at.isoformat()}".encode("utf-8")
        ).hexdigest()

    def save(self, post: PostSet, narration_script: str, narration_manually_edited: bool) -> str:
        payload = asdict(post)
        payload["selected_at"] = post.selected_at.isoformat()
        payload["article"]["source_path"] = str(post.article.source_path)
        raw = json.dumps(
            {"version": 1, "post": payload, "narration_script": narration_script,
             "narration_manually_edited": narration_manually_edited},
            ensure_ascii=False,
        )
        draft_id = self.draft_id(post)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO drafts (id, article_key, payload, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
                "updated_at=excluded.updated_at, completed=0",
                (draft_id, post.article.article_key, raw, datetime.now().astimezone().isoformat()),
            )
        return draft_id

    def list_drafts(self) -> list[Draft]:
        self.warnings = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM drafts WHERE completed=0 ORDER BY updated_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            try:
                raw = json.loads(row["payload"])
                _validate_payload(raw)
                if raw["version"] != 1:
                    raise ValueError("未対応の下書き形式")
                payload = raw["post"]
                article = payload.pop("article")
                article["source_path"] = Path(article["source_path"])
                article["content"] = tuple(ContentBlock(**item) for item in article["content"])
                payload["selected_at"] = datetime.fromisoformat(payload["selected_at"])
                payload["hashtags"] = tuple(payload["hashtags"])
                payload["source_points"] = tuple(payload["source_points"])
                post = PostSet(article=Article(**article), **payload)
                if not isinstance(post.tiktok_script, str) or not isinstance(raw["narration_script"], str):
                    raise ValueError("下書きの文章が不正")
                if not isinstance(raw["narration_manually_edited"], bool):
                    raise ValueError("下書きの編集状態が不正")
                result.append(Draft(row["id"], post, raw["narration_script"],
                                    raw["narration_manually_edited"], datetime.fromisoformat(row["updated_at"])))
            except (KeyError, TypeError, ValueError, AttributeError):
                self.warnings.append("読み取れない下書きがあります。保存データはそのまま残しています。")
        return result

    def complete_article(self, article_key: str) -> None:
        """投稿が確定した下書きは一覧から外す。保存内容は削除しない。"""
        with self._connect() as connection:
            connection.execute("UPDATE drafts SET completed=1 WHERE article_key=?", (article_key,))


def _validate_payload(raw: object) -> None:
    """JSONとして読めても、画面へ渡せない型のデータは復元しない。"""
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1:
        raise ValueError("下書きの形式が不正")
    post = raw.get("post")
    if not isinstance(post, dict) or not isinstance(post.get("article"), dict):
        raise ValueError("下書きの記事情報が不正")
    article = post["article"]
    for key in ("article_key", "concern", "gender", "mbti", "zodiac", "title", "sns_catchphrase", "source_path"):
        if not isinstance(article.get(key), str):
            raise ValueError("下書きの記事情報が不正")
    for key in ("selected_at", "tiktok_script", "x_post", "canonical_url", "tiktok_url", "x_url", "tiktok_template_id", "x_template_id"):
        if not isinstance(post.get(key), str):
            raise ValueError("下書きの投稿情報が不正")
    for key in ("hashtags", "source_points"):
        if not isinstance(post.get(key), list) or any(not isinstance(item, str) for item in post[key]):
            raise ValueError("下書きの投稿情報が不正")
    duration = post.get("estimated_tiktok_seconds")
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
        raise ValueError("下書きの音声時間が不正")
    if type(post.get("x_weighted_length")) is not int or post["x_weighted_length"] < 0:
        raise ValueError("下書きの文字数が不正")
    if not isinstance(article.get("content"), list):
        raise ValueError("下書きの記事本文が不正")
    for block in article["content"]:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str) or not isinstance(block.get("type"), str):
            raise ValueError("下書きの記事本文が不正")
        if block.get("rank") is not None and type(block["rank"]) is not int:
            raise ValueError("下書きの順位が不正")
        if block.get("desc") is not None and not isinstance(block["desc"], str):
            raise ValueError("下書きの記事説明が不正")
