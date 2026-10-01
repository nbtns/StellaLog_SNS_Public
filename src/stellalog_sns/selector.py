from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .models import Article, HistoryRecord, SelectionFilters


WEEKLY_QUOTAS = {
    "personality": 2,
    "ranking": 2,
    "love": 1,
    "work_money": 1,
    "reunion_night": 1,
}


class NoAvailableArticleError(LookupError):
    pass


class ArticleSelector:
    def __init__(self, weekly_quotas: dict[str, int] | None = None) -> None:
        self.weekly_quotas = dict(weekly_quotas or WEEKLY_QUOTAS)

    def choose(
        self,
        articles: Iterable[Article],
        filters: SelectionFilters,
        history_records: Iterable[HistoryRecord],
        session_seen: Iterable[str],
        now: datetime,
    ) -> Article:
        articles = tuple(articles)
        history = tuple(history_records)
        seen = set(session_seen)
        posted_keys = {
            str(_record_value(record, "article_key"))
            for record in history
            if bool(_record_value(record, "is_posted", False))
        }

        candidates = [article for article in articles if self._matches(article, filters)]
        if not filters.include_posted:
            candidates = [article for article in candidates if article.article_key not in posted_keys]
        if not candidates:
            if not filters.include_posted:
                raise NoAvailableArticleError(
                    "条件に合う未投稿記事がありません。条件を広げるか「投稿済みも含める」を選んでください。"
                )
            raise NoAvailableArticleError("条件に合う記事がありません。選定条件を広げてください。")

        unseen = [article for article in candidates if article.article_key not in seen]
        if not unseen:
            raise NoAvailableArticleError(
                "この条件の候補を一巡しました。選定条件を変えるか、候補の一巡を解除してください。"
            )
        candidates = unseen

        if filters.concern is None:
            preferred_group = self._preferred_group(candidates, history, now)
            grouped = [a for a in candidates if _category_group(a.concern) == preferred_group]
            if grouped:
                candidates = grouped

        preferred_categories = self._preferred_category_within_group(candidates, history, now)
        if preferred_categories:
            narrowed = [article for article in candidates if article.concern in preferred_categories]
            if narrowed:
                candidates = narrowed

        post_counts = Counter(
            str(_record_value(record, "article_key"))
            for record in history
            if bool(_record_value(record, "is_posted", False))
        )
        fewest_posts = min(post_counts[article.article_key] for article in candidates)
        candidates = [a for a in candidates if post_counts[a.article_key] == fewest_posts]

        switch_number = len(seen)
        day_key = now.date().isoformat()
        return min(
            candidates,
            key=lambda article: hashlib.sha256(
                f"{day_key}|{switch_number}|{article.article_key}".encode("utf-8")
            ).hexdigest(),
        )

    @staticmethod
    def _matches(article: Article, filters: SelectionFilters) -> bool:
        checks = (
            (article.concern, filters.concern),
            (article.mbti, filters.mbti),
            (article.zodiac, filters.zodiac),
            (article.gender, filters.gender),
        )
        return all(expected is None or actual == expected.lower() for actual, expected in checks)

    def _preferred_group(
        self,
        candidates: list[Article],
        history: tuple[HistoryRecord, ...],
        now: datetime,
    ) -> str:
        possible_groups = {_category_group(article.concern) for article in candidates}
        week_start = now.date() - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=7)
        weekly = [
            record
            for record in history
            if bool(_record_value(record, "is_posted", False))
            and week_start <= _record_datetime(record, "posted_at").date() < week_end
        ]
        counts = Counter(
            _category_group(str(_record_value(record, "category"))) for record in weekly
        )

        deficits = {
            group: self.weekly_quotas.get(group, 0) - counts[group]
            for group in possible_groups
        }
        largest_deficit = max(deficits.values())
        tied = {group for group, deficit in deficits.items() if deficit == largest_deficit}
        if len(tied) == 1:
            return next(iter(tied))

        def last_selected(group: str) -> datetime:
            dates = [
                _record_datetime(record, "selected_at")
                for record in weekly
                if _category_group(str(_record_value(record, "category"))) == group
            ]
            return max(dates) if dates else datetime.min

        return min(tied, key=lambda group: (last_selected(group), group))

    @staticmethod
    def _preferred_category_within_group(
        candidates: list[Article],
        history: tuple[HistoryRecord, ...],
        now: datetime,
    ) -> set[str]:
        categories = {article.concern for article in candidates}
        if not (categories <= {"work", "money"} or categories <= {"reunion", "night"}):
            return categories
        cutoff = now.date() - timedelta(days=90)
        counts = Counter(
            str(_record_value(record, "category"))
            for record in history
            if bool(_record_value(record, "is_posted", False))
            and _record_datetime(record, "posted_at").date() >= cutoff
            and str(_record_value(record, "category")) in categories
        )
        fewest = min(counts[category] for category in categories)
        return {category for category in categories if counts[category] == fewest}


def _category_group(concern: str) -> str:
    if concern in {"work", "money"}:
        return "work_money"
    if concern in {"reunion", "night"}:
        return "reunion_night"
    return concern


def _record_value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _record_datetime(record: Any, name: str) -> datetime:
    value = _record_value(record, name)
    if isinstance(value, datetime):
        # Date comparisons are deliberately local-calendar based. Removing the
        # timezone avoids mixing aware and naive datetimes only for tie sorting.
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.min
