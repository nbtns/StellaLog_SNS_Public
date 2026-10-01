from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from stellalog_sns import generator
from stellalog_sns.labels import MBTI_VALUES, ZODIAC_LABELS
from stellalog_sns.models import Article, ContentBlock
from stellalog_sns.ranking_pilot import build_ranking_pilot
from stellalog_sns.url_builder import x_weighted_length
from stellalog_sns.video_renderer import split_subtitle_cards
from stellalog_sns.x_thread import split_x_thread


@pytest.fixture
def article() -> Article:
    path = Path(__file__).parent / "fixtures" / "infj_cancer_ranking.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Article(
        article_key="ranking/unisex/infj/cancer",
        concern=payload["concern"], gender=payload["gender"],
        mbti=payload["mbti"], zodiac=payload["zodiac"],
        title=payload["title"], sns_catchphrase=payload["sns_catchphrase"],
        source_path=path,
        content=tuple(ContentBlock(**block) for block in payload["content"]),
    )


def test_pilot_keeps_each_first_place_with_its_own_reason(article: Article) -> None:
    post = generator.PostGenerator().generate(article, "https://n-stellalog.com")
    compact = post.tiktok_script.replace("\n", "")
    best, worst = compact.split("地雷相性1位は", 1)
    assert "神相性1位はENTP射手座" in best
    assert "世話をする役割から解放してくれる" in best
    assert "深い話にも応えてくれる" in best
    assert worst.startswith("ESTP牡羊座")
    assert "あなたは深い絆を確かめたい" in worst
    assert "今この瞬間の自由" in worst
    assert "重いと受け取られて" in worst
    assert "StellaLog独自" not in compact
    assert post.tiktok_script.split("\n\n")[1] == "神相性1位は\nENTP射手座"
    assert "INFJ蟹座の恋愛相性" in compact
    assert "ENTP射手座が相性1位になる理由" not in compact
    assert "4位" not in compact
    assert "ENFJ獅子座" not in compact
    assert "友達" not in compact
    assert "仕事" not in compact
    assert "×" not in compact


def test_x_posts_explain_best_and_worst_separately(article: Article) -> None:
    post = generator.PostGenerator().generate(article, "https://n-stellalog.com")
    first, second = split_x_thread(post.x_post)
    assert "【神相性1位：ENTP×射手座】" in first
    assert "世話をする側から解放" in first
    assert "深い会話にも応えて" in first
    assert "【地雷相性1位：ESTP×牡羊座】" in second
    assert "深い絆" in second and "今この瞬間の自由" in second
    assert "あなたの執着が強まる" in second
    assert all(x_weighted_length(part) <= 280 for part in (first, second))
    assert second.endswith(post.x_url)
    assert "utm_source=x" in post.x_url
    assert "4位" not in post.x_post
    assert "ENFJ×獅子座" not in post.x_post


def test_pilot_subtitles_fit_and_keep_the_existing_video_duration(article: Article) -> None:
    post = generator.PostGenerator().generate(article, "https://n-stellalog.com")
    cards = tuple(tuple(card.splitlines()) for card in post.tiktok_script.split("\n\n"))
    assert 60 <= post.estimated_tiktok_seconds <= 75
    assert all(1 <= len(card) <= 5 for card in cards)
    assert all(len(line) <= 13 for card in cards for line in card)
    assert split_subtitle_cards(post.tiktok_script) == cards


def test_sources_are_only_the_two_love_first_places_and_their_paragraphs(article: Article) -> None:
    post = generator.PostGenerator().generate(article, "https://n-stellalog.com")
    assert len(post.source_points) == 6
    assert post.source_points[0] == "ENTP × 射手座"
    assert post.source_points[3] == "ESTP × 牡羊座"
    source_texts = {block.text for block in article.content}
    assert all(point in source_texts for point in post.source_points)
    assert not any("ENFJ × 獅子座" in point for point in post.source_points)


@pytest.mark.parametrize("index", (5, 6))
def test_changed_first_place_or_reason_requires_review(article: Article, index: int) -> None:
    blocks = list(article.content)
    assert blocks[index].type in {"ranking", "p"}
    blocks[index] = replace(blocks[index], text="更新された順位または説明")
    with pytest.raises(ValueError, match="更新されています"):
        generator.PostGenerator().generate(
            replace(article, content=tuple(blocks)), "https://n-stellalog.com"
        )


def test_fourth_place_edits_cannot_change_pilot_material(article: Article) -> None:
    original = build_ranking_pilot(article, "https://example.com/article")
    blocks = tuple(
        replace(block, desc="4位の説明を更新")
        if block.type == "ranking" and block.rank == 4 else block
        for block in article.content
    )
    assert build_ranking_pilot(
        replace(article, content=blocks), "https://example.com/article"
    ) == original


def test_other_191_ranking_types_do_not_use_pilot(article: Article) -> None:
    checked = 0
    for mbti in MBTI_VALUES:
        for zodiac in ZODIAC_LABELS:
            if (mbti, zodiac) == ("infj", "cancer"):
                continue
            other = replace(
                article, article_key=f"ranking/unisex/{mbti}/{zodiac}",
                mbti=mbti, zodiac=zodiac,
            )
            assert build_ranking_pilot(other, "https://example.com/article") is None
            checked += 1
    assert checked == 191


def test_nonranking_generation_is_unchanged(article: Article, monkeypatch: pytest.MonkeyPatch) -> None:
    other = replace(article, article_key="personality/unisex/infj/cancer", concern="personality")
    service = generator.PostGenerator()
    selected_at = datetime(2026, 9, 13, 12)
    actual = service.generate(other, "https://n-stellalog.com", selected_at=selected_at)
    monkeypatch.setattr(generator, "build_ranking_posts", lambda article, x_url, **kwargs: None)
    baseline = service.generate(other, "https://n-stellalog.com", selected_at=selected_at)
    assert actual == baseline
