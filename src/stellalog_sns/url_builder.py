from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, urlunsplit

from .models import Article


_SAFE_PART = re.compile(r"^[a-z0-9-]+$")
_URL_TOKEN = re.compile(r"https?://[^\s]+")


def normalize_site_origin(site_origin: str) -> str:
    origin = site_origin.strip().rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("公開サイトURLはhttp://またはhttps://から入力してください")
    if parsed.query or parsed.fragment:
        raise ValueError("公開サイトURLにクエリ文字列や#以降は指定できません")
    clean_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", ""))


def build_canonical_url(article: Article, site_origin: str) -> str:
    parts = (article.mbti, article.zodiac, article.gender, article.concern)
    if any(not _SAFE_PART.fullmatch(part) for part in parts):
        raise ValueError("記事URLに使用できない値が含まれています")
    return f"{normalize_site_origin(site_origin)}/reading/{'/'.join(parts)}"


def build_tracking_url(article: Article, site_origin: str, source: str) -> str:
    if source not in {"tiktok", "x"}:
        raise ValueError("utm_sourceはtiktokまたはxを指定してください")
    canonical = build_canonical_url(article, site_origin)
    content = "_".join((article.concern, article.mbti, article.zodiac, article.gender))
    query = urlencode(
        {
            "utm_source": source,
            "utm_medium": "social",
            "utm_campaign": "192types",
            "utm_content": content,
        }
    )
    return f"{canonical}?{query}"


def build_article_urls(article: Article, site_origin: str) -> tuple[str, str, str]:
    canonical = build_canonical_url(article, site_origin)
    return (
        canonical,
        build_tracking_url(article, site_origin, "tiktok"),
        build_tracking_url(article, site_origin, "x"),
    )


def x_weighted_length(text: str) -> int:
    """Return a conservative X-style weighted length (URLs count as 23)."""

    total = 0
    cursor = 0
    for match in _URL_TOKEN.finditer(text):
        total += _weighted_non_url(text[cursor : match.start()])
        total += 23
        cursor = match.end()
    return total + _weighted_non_url(text[cursor:])


def _weighted_non_url(text: str) -> int:
    # X counts most Latin characters as one and CJK/emoji as two.  The ranges
    # below mirror the documented single-weight ranges closely enough for an
    # offline guard; treating everything else as two is deliberately safe.
    single_weight_ranges = (
        (0x0000, 0x10FF),
        (0x2000, 0x200D),
        (0x2010, 0x201F),
        (0x2032, 0x2037),
    )
    return sum(
        1
        if any(start <= ord(character) <= end for start, end in single_weight_ranges)
        else 2
        for character in text
    )
