from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from stellalog_sns.models import Article
from stellalog_sns.url_builder import (
    build_article_urls,
    build_canonical_url,
    build_tracking_url,
    x_weighted_length,
)


def _article() -> Article:
    return Article(
        article_key="love/female/enfj/aquarius",
        concern="love",
        gender="female",
        mbti="enfj",
        zodiac="aquarius",
        title="title",
        content=(),
        sns_catchphrase="catch",
        source_path=Path("article.json"),
    )


def test_builds_current_route_in_correct_order() -> None:
    assert build_canonical_url(_article(), "https://n-stellalog.com/") == (
        "https://n-stellalog.com/reading/enfj/aquarius/female/love"
    )


@pytest.mark.parametrize("source", ["tiktok", "x"])
def test_tracking_url_has_expected_utm(source: str) -> None:
    url = build_tracking_url(_article(), "https://n-stellalog.com", source)
    query = parse_qs(urlsplit(url).query)
    assert query == {
        "utm_source": [source],
        "utm_medium": ["social"],
        "utm_campaign": ["192types"],
        "utm_content": ["love_enfj_aquarius_female"],
    }


def test_build_article_urls_returns_both_media_urls() -> None:
    canonical, tiktok, x = build_article_urls(_article(), "https://n-stellalog.com")
    assert "?" not in canonical
    assert "utm_source=tiktok" in tiktok
    assert "utm_source=x" in x


def test_x_weight_counts_url_as_23_and_japanese_as_two() -> None:
    assert x_weighted_length("abc あ https://example.com/very/long") == 3 + 1 + 2 + 1 + 23


def test_rejects_invalid_origin() -> None:
    with pytest.raises(ValueError):
        build_canonical_url(_article(), "n-stellalog.com")
