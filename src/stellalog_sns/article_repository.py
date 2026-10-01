from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import Article, ArticleLoadResult, ContentBlock


_SAFE_PART = re.compile(r"^[a-z0-9-]+$")
_KNOWN_CONTENT_TYPES = {"h3", "h4", "p", "cta", "ranking"}


class ArticleRepository:
    """Read-only access to the StellaLog article data directory."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser()

    def load_all(self) -> ArticleLoadResult:
        warnings: list[str] = []
        index_path = self.data_dir / "article-index.json"
        article_root = self.data_dir / "articles"

        if not index_path.is_file():
            return ArticleLoadResult(
                articles=(),
                warnings=(f"article-index.jsonが見つかりません: {index_path}",),
                indexed_count=0,
            )
        if not article_root.is_dir():
            return ArticleLoadResult(
                articles=(),
                warnings=(f"articlesフォルダが見つかりません: {article_root}",),
                indexed_count=0,
            )

        try:
            raw_index = json.loads(index_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return ArticleLoadResult(
                articles=(),
                warnings=(f"article-index.jsonを読み込めません: {exc}",),
                indexed_count=0,
            )

        if not isinstance(raw_index, list):
            return ArticleLoadResult(
                articles=(),
                warnings=("article-index.jsonの形式が正しくありません（配列が必要です）",),
                indexed_count=0,
            )

        indexed_count = len(raw_index)
        articles: list[Article] = []
        seen_keys: set[str] = set()
        resolved_root = article_root.resolve()

        for position, raw_key in enumerate(raw_index, start=1):
            parsed = self._parse_key(raw_key)
            if parsed is None:
                warnings.append(f"インデックス{position}件目のパス形式が不正です: {raw_key!r}")
                continue
            concern, gender, mbti, zodiac = parsed
            article_key = "/".join(parsed)
            if article_key in seen_keys:
                warnings.append(f"重複した記事を読み飛ばしました: {article_key}")
                continue
            seen_keys.add(article_key)

            source_path = article_root.joinpath(concern, gender, mbti, f"{zodiac}.json")
            try:
                resolved_path = source_path.resolve()
                resolved_path.relative_to(resolved_root)
            except (OSError, ValueError):
                warnings.append(f"記事フォルダ外を指すパスを拒否しました: {article_key}")
                continue

            article, article_warnings = self._load_one(
                resolved_path,
                article_key=article_key,
                expected=(concern, gender, mbti, zodiac),
            )
            warnings.extend(article_warnings)
            if article is not None:
                articles.append(article)

        return ArticleLoadResult(
            articles=tuple(articles),
            warnings=tuple(warnings),
            indexed_count=indexed_count,
        )

    @staticmethod
    def _parse_key(raw_key: Any) -> tuple[str, str, str, str] | None:
        if not isinstance(raw_key, str):
            return None
        parts = raw_key.split("/")
        if len(parts) != 4 or any(not _SAFE_PART.fullmatch(part) for part in parts):
            return None
        return parts[0], parts[1], parts[2], parts[3]

    @staticmethod
    def _load_one(
        source_path: Path,
        *,
        article_key: str,
        expected: tuple[str, str, str, str],
    ) -> tuple[Article | None, list[str]]:
        warnings: list[str] = []
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None, [f"記事ファイルが見つかりません: {article_key}"]
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return None, [f"記事JSONを読み込めません ({article_key}): {exc}"]

        if not isinstance(payload, dict):
            return None, [f"記事JSONの形式が正しくありません: {article_key}"]

        concern, gender, mbti, zodiac = expected
        expected_values = {
            "concern": concern,
            "gender": gender,
            "mbti": mbti,
            "zodiac": zodiac,
        }
        for field_name, expected_value in expected_values.items():
            if payload.get(field_name) != expected_value:
                return None, [
                    f"記事パスと{field_name}が一致しないため読み飛ばしました: {article_key}"
                ]

        title = payload.get("title")
        catchphrase = payload.get("sns_catchphrase")
        raw_content = payload.get("content")
        if not isinstance(title, str) or not title.strip():
            return None, [f"記事タイトルが空です: {article_key}"]
        if not isinstance(catchphrase, str) or not catchphrase.strip():
            return None, [f"sns_catchphraseが空です: {article_key}"]
        if not isinstance(raw_content, list):
            return None, [f"contentが配列ではありません: {article_key}"]

        blocks: list[ContentBlock] = []
        unknown_types: set[str] = set()
        for item in raw_content:
            if not isinstance(item, dict):
                continue
            block_type = item.get("type")
            if block_type not in _KNOWN_CONTENT_TYPES:
                if isinstance(block_type, str):
                    unknown_types.add(block_type)
                continue
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            rank = item.get("rank") if block_type == "ranking" else None
            if not isinstance(rank, int):
                rank = None
            desc = item.get("desc") if block_type == "ranking" else None
            if not isinstance(desc, str) or not desc.strip():
                desc = None
            blocks.append(
                ContentBlock(type=block_type, text=text.strip(), rank=rank, desc=desc)
            )

        if not any(block.type in {"h3", "h4", "p", "ranking"} for block in blocks):
            return None, [f"投稿文に使える本文がありません: {article_key}"]
        if unknown_types:
            warnings.append(
                f"未知のcontent.typeを読み飛ばしました ({article_key}): "
                + ", ".join(sorted(unknown_types))
            )

        return (
            Article(
                article_key=article_key,
                concern=concern,
                gender=gender,
                mbti=mbti,
                zodiac=zodiac,
                title=title.strip(),
                content=tuple(blocks),
                sns_catchphrase=catchphrase.strip(),
                source_path=source_path,
            ),
            warnings,
        )
