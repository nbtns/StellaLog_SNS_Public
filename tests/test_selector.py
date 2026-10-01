from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from stellalog_sns.models import Article, SelectionFilters
from stellalog_sns.selector import ArticleSelector, NoAvailableArticleError


def _article(concern: str, suffix: str = "aries", gender: str = "unisex") -> Article:
    return Article(
        article_key=f"{concern}/{gender}/infj/{suffix}",
        concern=concern,
        gender=gender,
        mbti="infj",
        zodiac=suffix,
        title=f"{concern}-{suffix}",
        content=(),
        sns_catchphrase="catch",
        source_path=Path(f"{suffix}.json"),
    )


def _history(article: Article, when: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        article_key=article.article_key,
        category=article.concern,
        selected_at=when,
        posted_at=when,
        is_posted=True,
    )


def test_weekly_quota_prefers_largest_shortfall() -> None:
    now = datetime(2026, 9, 2, 12)
    personality = _article("personality")
    ranking = _article("ranking")
    love = _article("love", gender="female")
    history = [_history(personality, now - timedelta(days=1))]

    chosen = ArticleSelector().choose(
        [personality, ranking, love], SelectionFilters(include_posted=True), history, set(), now
    )

    assert chosen.concern == "ranking"


def test_explicit_category_overrides_weekly_balance() -> None:
    now = datetime(2026, 9, 2, 12)
    articles = [_article("personality"), _article("night", gender="male")]
    chosen = ArticleSelector().choose(
        articles,
        SelectionFilters(concern="night"),
        [],
        set(),
        now,
    )
    assert chosen.concern == "night"


def test_posted_and_session_seen_are_excluded() -> None:
    now = datetime(2026, 9, 2, 12)
    first = _article("personality", "aries")
    second = _article("personality", "taurus")
    history = [_history(first, now - timedelta(days=1))]
    chosen = ArticleSelector().choose(
        [first, second], SelectionFilters(), history, set(), now
    )
    assert chosen == second

    with pytest.raises(NoAvailableArticleError, match="一巡"):
        ArticleSelector().choose(
            [first, second], SelectionFilters(), history, {second.article_key}, now
        )


def test_work_money_uses_less_posted_category_in_last_90_days() -> None:
    now = datetime(2026, 9, 2, 12)
    work = _article("work", gender="male")
    money = _article("money")
    old_money = _article("money", "taurus")
    history = [_history(old_money, now - timedelta(days=10))]

    chosen = ArticleSelector().choose(
        [work, money], SelectionFilters(include_posted=True), history, set(), now
    )
    assert chosen.concern == "work"
