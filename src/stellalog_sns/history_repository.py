"""SQLiteを使った投稿履歴の永続化。"""

from __future__ import annotations

from datetime import date, datetime, time
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from .models import HistoryRecord, PostSet
from .settings import default_app_data_dir


DATABASE_FILE_NAME = "history.sqlite3"


class AlreadyPostedError(ValueError):
    """同じ記事を重複して投稿済みにしようとした場合のエラー。"""


class HistoryRepository:
    """投稿済みと確定した投稿セットだけを保存します。

    ``app_dir`` を省略した場合は
    ``%LOCALAPPDATA%\\StellaLogSNSStudio`` を使用します。テストや移行時は
    任意のフォルダを渡せます。
    """

    def __init__(self, app_dir: Path | str | None = None) -> None:
        self.app_dir = Path(app_dir) if app_dir is not None else default_app_data_dir()
        self.path = self.app_dir / DATABASE_FILE_NAME
        self.recovery_dir = self.app_dir / "recovery"
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self._recover_if_corrupt()
        self._create_schema()

    def mark_posted(
        self,
        post_set: PostSet,
        *,
        posted_at: datetime | None = None,
        memo: str = "",
    ) -> HistoryRecord:
        """画面で「投稿済みにする」が押された投稿セットを確定保存します。"""

        confirmed_at = posted_at or datetime.now().astimezone()
        values = (
            post_set.article.article_key,
            post_set.selected_at.isoformat(),
            confirmed_at.isoformat(),
            post_set.article.concern,
            post_set.article.mbti,
            post_set.article.zodiac,
            post_set.article.gender,
            post_set.article.title,
            str(post_set.article.source_path),
            post_set.canonical_url,
            post_set.tiktok_url,
            post_set.x_url,
            post_set.tiktok_script,
            post_set.x_post,
            json.dumps(list(post_set.hashtags), ensure_ascii=False),
            post_set.tiktok_template_id,
            post_set.x_template_id,
            1,
            memo,
        )
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO post_history (
                        article_key, selected_at, posted_at, category, mbti, zodiac,
                        gender, article_title, source_path, public_url, tiktok_url,
                        x_url, tiktok_script, x_post, hashtags, tiktok_template_id,
                        x_template_id, is_posted, memo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                record_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise AlreadyPostedError(
                f"この記事はすでに投稿済みです: {post_set.article.title}"
            ) from error

        record = self.get(record_id)
        if record is None:  # pragma: no cover - SQLiteの異常時だけ到達
            raise RuntimeError("保存した投稿履歴を読み直せませんでした")
        return record

    def get(self, record_id: int) -> HistoryRecord | None:
        """IDを指定して投稿履歴を1件取得します。"""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM post_history WHERE id = ?", (record_id,)
            ).fetchone()
        return self._to_record(row) if row is not None else None

    def list_records(
        self,
        *,
        query: str = "",
        category: str | None = None,
        mbti: str | None = None,
        zodiac: str | None = None,
        gender: str | None = None,
        date_from: date | datetime | str | None = None,
        date_to: date | datetime | str | None = None,
        is_posted: bool | None = None,
        limit: int | None = None,
    ) -> list[HistoryRecord]:
        """履歴を新しい順で検索・絞り込みします。"""

        clauses: list[str] = []
        parameters: list[Any] = []
        cleaned_query = query.strip()
        if cleaned_query:
            clauses.append(
                "(article_title LIKE ? OR article_key LIKE ? OR category LIKE ? "
                "OR mbti LIKE ? OR zodiac LIKE ? OR memo LIKE ?)"
            )
            like = f"%{cleaned_query}%"
            parameters.extend([like] * 6)

        for column, value in (
            ("category", category),
            ("mbti", mbti),
            ("zodiac", zodiac),
            ("gender", gender),
        ):
            if value:
                clauses.append(f"{column} = ?")
                parameters.append(value)

        if date_from is not None:
            clauses.append("posted_at >= ?")
            parameters.append(self._date_boundary(date_from, end=False))
        if date_to is not None:
            clauses.append("posted_at <= ?")
            parameters.append(self._date_boundary(date_to, end=True))
        if is_posted is not None:
            clauses.append("is_posted = ?")
            parameters.append(1 if is_posted else 0)

        sql = "SELECT * FROM post_history"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY posted_at DESC, id DESC"
        if limit is not None:
            if limit < 0:
                raise ValueError("limitは0以上で指定してください")
            sql += " LIMIT ?"
            parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._to_record(row) for row in rows]

    def is_posted(self, article_key: str) -> bool:
        """記事が現在投稿済みとして記録されているか返します。"""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM post_history WHERE article_key = ? AND is_posted = 1 LIMIT 1",
                (article_key,),
            ).fetchone()
        return row is not None

    def posted_article_keys(self) -> set[str]:
        """自動選定から除外する投稿済み記事キーを返します。"""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT article_key FROM post_history WHERE is_posted = 1"
            ).fetchall()
        return {str(row["article_key"]) for row in rows}

    def update_memo(self, record_id: int, memo: str) -> bool:
        """履歴のメモを更新し、対象が存在したか返します。"""

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE post_history SET memo = ? WHERE id = ?", (memo, record_id)
            )
        return cursor.rowcount > 0

    def unmark_posted(self, record_id: int) -> bool:
        """誤って確定した履歴を投稿済み対象から外します（履歴自体は残します）。"""

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE post_history SET is_posted = 0 WHERE id = ? AND is_posted = 1",
                (record_id,),
            )
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS post_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_key TEXT NOT NULL,
                    selected_at TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    mbti TEXT NOT NULL,
                    zodiac TEXT NOT NULL,
                    gender TEXT NOT NULL,
                    article_title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    public_url TEXT NOT NULL,
                    tiktok_url TEXT NOT NULL,
                    x_url TEXT NOT NULL,
                    tiktok_script TEXT NOT NULL,
                    x_post TEXT NOT NULL,
                    hashtags TEXT NOT NULL,
                    tiktok_template_id TEXT NOT NULL,
                    x_template_id TEXT NOT NULL,
                    is_posted INTEGER NOT NULL DEFAULT 1 CHECK (is_posted IN (0, 1)),
                    memo TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_post_history_active_article
                    ON post_history(article_key) WHERE is_posted = 1;
                CREATE INDEX IF NOT EXISTS ix_post_history_posted_at
                    ON post_history(posted_at DESC);
                CREATE INDEX IF NOT EXISTS ix_post_history_filters
                    ON post_history(category, mbti, zodiac, gender, is_posted);
                """
            )

    def _recover_if_corrupt(self) -> None:
        if not self.path.exists():
            return
        try:
            connection = sqlite3.connect(self.path)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if result is None or result[0] != "ok":
                    raise sqlite3.DatabaseError("SQLite quick_check failed")
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            self.recovery_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            destination = self.recovery_dir / f"history-corrupt-{stamp}.sqlite3"
            shutil.move(str(self.path), str(destination))
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(f"{self.path}{suffix}")
                if sidecar.exists():
                    shutil.move(
                        str(sidecar),
                        str(self.recovery_dir / f"{destination.name}{suffix}"),
                    )

    @staticmethod
    def _date_boundary(value: date | datetime | str, *, end: bool) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            boundary_time = time.max if end else time.min
            return datetime.combine(value, boundary_time).isoformat()
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("日付に空文字は指定できません")
            if "T" not in stripped and " " not in stripped:
                parsed_date = date.fromisoformat(stripped)
                parsed = datetime.combine(parsed_date, time.max if end else time.min)
            else:
                parsed = datetime.fromisoformat(stripped)
            return parsed.isoformat()
        raise TypeError("日付はdate、datetime、ISO形式文字列で指定してください")

    @staticmethod
    def _to_record(row: sqlite3.Row) -> HistoryRecord:
        try:
            hashtags_raw = json.loads(row["hashtags"])
        except (TypeError, json.JSONDecodeError):
            hashtags_raw = []
        hashtags = tuple(str(item) for item in hashtags_raw) if isinstance(hashtags_raw, list) else ()
        return HistoryRecord(
            id=int(row["id"]),
            article_key=str(row["article_key"]),
            selected_at=datetime.fromisoformat(row["selected_at"]),
            posted_at=datetime.fromisoformat(row["posted_at"]),
            category=str(row["category"]),
            mbti=str(row["mbti"]),
            zodiac=str(row["zodiac"]),
            gender=str(row["gender"]),
            article_title=str(row["article_title"]),
            source_path=str(row["source_path"]),
            public_url=str(row["public_url"]),
            tiktok_url=str(row["tiktok_url"]),
            x_url=str(row["x_url"]),
            tiktok_script=str(row["tiktok_script"]),
            x_post=str(row["x_post"]),
            hashtags=hashtags,
            tiktok_template_id=str(row["tiktok_template_id"]),
            x_template_id=str(row["x_template_id"]),
            is_posted=bool(row["is_posted"]),
            memo=str(row["memo"]),
        )
