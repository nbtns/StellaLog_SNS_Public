"""恋愛の神相性・地雷相性を、順位と理由の対応を保って投稿にする。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from .labels import format_mbti_zodiac, remove_mbti_zodiac_crosses
from .models import Article
from .ranking_pilot import (
    RankingPilot,
    _first_rank_in_section,
    _ranking_source_points,
    build_ranking_pilot,
)
from .url_builder import x_weighted_length


_COPY_DIRECTORY = Path(__file__).resolve().parent / "assets" / "ranking_copy"
_X_TRANSITION = "一方、すれ違いやすい相手は…"
_X_OUTRO = "詳しい続きはStellaLogの記事でどうぞ。"


@lru_cache(maxsize=1)
def _load_reviewed_copy() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in sorted(_COPY_DIRECTORY.glob("group_*.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        for key, entry in group.items():
            if key in result:
                raise ValueError(f"相性ランキングの文章が重複しています: {key}")
            if not isinstance(entry.get("hook"), str) or not entry["hook"].strip():
                raise ValueError(f"相性ランキングの冒頭文を確認してください: {key}")
            for kind in ("best", "worst"):
                sentences = entry.get(kind)
                if (
                    not isinstance(sentences, list) or len(sentences) != 3
                    or any(not isinstance(s, str) or not s.strip() for s in sentences)
                ):
                    raise ValueError(f"相性ランキングの理由を確認してください: {key}")
            result[key] = entry
    return result


def _x_post(header: str, reasons: list[str], footer: str) -> str:
    # 必ず理由の初めから使い、文の途中を切らずに2～3文を載せる。
    selected: list[str] = []
    for reason in reasons:
        candidate = f"{header}\n{''.join((*selected, reason))}\n\n{footer}"
        if x_weighted_length(candidate) > 280:
            break
        selected.append(reason)
    if len(selected) < 2:
        raise ValueError("相性の理由2文をXの文字数内に収められません。文章を見直してください。")
    return f"{header}\n{''.join(selected)}\n\n{footer}"


def build_ranking_posts(
    article: Article,
    x_url: str,
    *,
    format_tiktok: Callable[[str], str],
) -> RankingPilot | None:
    if article.concern != "ranking":
        return None
    # 利用者が確認したINFJ蟹座の文章・字幕配置はそのまま使う。
    reviewed_pilot = build_ranking_pilot(article, x_url)
    if reviewed_pilot is not None:
        return reviewed_pilot

    source_points = _ranking_source_points(article)
    entry = _load_reviewed_copy().get(article.article_key)
    signature = hashlib.sha256(
        json.dumps(source_points, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if entry is None or entry.get("source_sha256") != signature:
        raise ValueError(
            f"{format_mbti_zodiac(article.mbti, article.zodiac)}の恋愛相性1位か、"
            "その説明が未確認または更新されています。元記事に合わせて投稿文を見直してください。"
        )

    best = _first_rank_in_section(article, "神相性")
    worst = _first_rank_in_section(article, "地雷相性")
    best_x = re.sub(r"\s+", "", best[0])
    worst_x = re.sub(r"\s+", "", worst[0])
    own_type = format_mbti_zodiac(article.mbti, article.zodiac)
    own_x = own_type.replace(article.mbti.upper(), f"{article.mbti.upper()}×", 1)
    blocks = (
        f"{entry['hook']}\n{own_type}の恋愛相性",
        f"神相性1位は\n{remove_mbti_zodiac_crosses(best_x)}",
        *entry["best"],
        f"一方で\n地雷相性1位は\n{remove_mbti_zodiac_crosses(worst_x)}",
        *entry["worst"],
        "当てはまるところはありますか？\n詳しい続きは\n「StellaLog」で\n検索してね",
    )
    script = remove_mbti_zodiac_crosses(format_tiktok("\n\n".join(blocks)))
    first = _x_post(
        f"{own_x}の恋愛相性\n\n【神相性1位：{best_x}】",
        entry["best"], _X_TRANSITION,
    )
    second = _x_post(
        f"【地雷相性1位：{worst_x}】", entry["worst"], f"{_X_OUTRO}\n{x_url}",
    )
    return RankingPilot(script, first, second, source_points)
