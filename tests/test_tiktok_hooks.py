from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from stellalog_sns import generator
from stellalog_sns.models import Article, ContentBlock


def _article(concern: str = "personality", *, catchphrase: str | None = None) -> Article:
    return Article(
        article_key=f"{concern}/unisex/infp/pisces",
        concern=concern,
        gender="unisex",
        mbti="infp",
        zodiac="pisces",
        title="INFP×魚座の記事タイトル",
        sns_catchphrase=(
            "笑顔の奥で考えすぎている" if catchphrase is None else catchphrase
        ),
        source_path=Path("article.json"),
        content=(
            ContentBlock("h3", "人の気持ちを先回りして考える"),
            ContentBlock(
                "p",
                "相手の表情や言葉を丁寧に受け取ります。自分より相手を優先することがあります。",
            ),
            ContentBlock("h3", "一方で本音を後回しにする矛盾"),
            ContentBlock("p", "気づかないうちに無理を重ねることがあります。"),
            ContentBlock("h3", "強みを活かすために必要なこと"),
            ContentBlock("p", "自分の希望も短い言葉で伝える方法があります。"),
        ),
    )


def _compact(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize(
    ("concern", "theme"),
    (
        ("personality", "性格"),
        ("love", "恋愛"),
        ("work", "仕事"),
        ("money", "金運"),
        ("reunion", "復縁"),
        ("night", "夜"),
        ("ranking", "相性"),
    ),
)
def test_hook_leads_with_article_phrase_and_identifies_target_and_theme(
    concern: str, theme: str
) -> None:
    article = _article(concern)
    old_heading = f"INFP魚座の\n{generator.TIKTOK_HEADLINE_LABELS[concern]}"
    if concern == "ranking":
        old_heading += "\nStellaLog独自\nランキング"
    body = "INFP魚座の\nあなたは\n人の気持ちを\n先回りして考える"
    script = f"{old_heading}\n\n{body}"

    result = generator._apply_tiktok_hook(article, script)
    opening, unchanged_body = result.split("\n\n", 1)
    compact_opening = _compact(opening)

    assert compact_opening.startswith(article.sns_catchphrase)
    assert f"INFP魚座の{theme}" in compact_opening
    assert generator.TIKTOK_HEADLINE_LABELS[concern] not in compact_opening
    assert unchanged_body == body
    assert "×" not in opening


def test_hook_preserves_every_body_card_including_reviewed_six_line_layout() -> None:
    body = (
        "全身で笑っているのに\n心の奥に薄い霧が\nかかっている\n感覚を\nそのまま\n大切にします"
        "\n\n友人の悲しみを\n聞くだけで\n自分の胸が\n物理的に重くなり"
        "\n\n当てはまるところは\nありますか？\n詳しい続きは\nStellaLogの記事でどうぞ"
    )
    script = f"INFP魚座の\n本当の性格\n\n{body}"

    result = generator._apply_tiktok_hook(_article(), script)

    assert result.split("\n\n", 1)[1] == body
    assert len(result.split("\n\n")[1].splitlines()) == 6


def test_ranking_hook_distinguishes_own_type_from_compatible_partner() -> None:
    article = _article(
        "ranking", catchphrase="一番相性が良いのはENFJ×蠍座！"
    )
    body = "1位\nENFJ蠍座\n自然体で気持ちを\n話せる相手です"
    script = (
        "INFP魚座の\n意外なランキング\nStellaLog独自\nランキング\n\n"
        f"{body}"
    )

    result = generator._apply_tiktok_hook(article, script)
    opening, unchanged_body = result.split("\n\n", 1)
    compact_opening = _compact(opening)

    assert "ENFJ蠍座" in compact_opening
    assert "相性1位になる理由" in compact_opening
    assert "INFP魚座の相性" in compact_opening
    assert "StellaLog独自ランキング" in compact_opening
    assert opening.splitlines()[-2:] == ["StellaLog独自", "ランキング"]
    assert "ENFJ蠍座の相性" not in compact_opening
    assert "×" not in opening
    assert unchanged_body == body


@pytest.mark.parametrize("catchphrase", ("", " \n\t "))
def test_missing_catchphrase_keeps_original_script(catchphrase: str) -> None:
    script = "INFP魚座の\n本当の性格\n\n編集済みの\n本文を残します"

    assert generator._apply_tiktok_hook(
        _article(catchphrase=catchphrase), script
    ) == script


def test_distinct_article_phrases_produce_distinct_hooks_for_same_mbti() -> None:
    first = _article(catchphrase="笑顔の奥で考えすぎている")
    second = replace(
        first,
        article_key="personality/unisex/infp/aries",
        zodiac="aries",
        sns_catchphrase="静かに見えて心の中では負けず嫌い",
    )
    body = "本文の\n内容は同じです"

    first_script = generator._apply_tiktok_hook(
        first, f"INFP魚座の\n本当の性格\n\n{body}"
    )
    second_script = generator._apply_tiktok_hook(
        second, f"INFP牡羊座の\n本当の性格\n\n{body}"
    )
    first_opening = _compact(first_script.split("\n\n", 1)[0])
    second_opening = _compact(second_script.split("\n\n", 1)[0])

    assert first_opening.startswith(first.sns_catchphrase)
    assert second_opening.startswith(second.sns_catchphrase)
    assert "INFP魚座の性格" in first_opening
    assert "INFP牡羊座の性格" in second_opening


def test_generation_changes_only_hook_and_duration_not_body_x_or_selected_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = _article("love")
    selected_at = datetime(2026, 9, 13, 9)
    service = generator.PostGenerator()
    changed = service.generate(
        article, "https://n-stellalog.com", selected_at=selected_at
    )
    monkeypatch.setattr(generator, "_apply_tiktok_hook", lambda article, script: script)
    baseline = service.generate(
        article, "https://n-stellalog.com", selected_at=selected_at
    )
    changed_opening, changed_body = changed.tiktok_script.split("\n\n", 1)
    original_opening, original_body = baseline.tiktok_script.split("\n\n", 1)

    assert changed_opening != original_opening
    assert changed_body == original_body
    assert changed.x_post == baseline.x_post
    assert changed.source_points == baseline.source_points
    assert changed.x_template_id == baseline.x_template_id
    assert changed.tiktok_template_id == baseline.tiktok_template_id
    assert changed.hashtags == baseline.hashtags
    assert (changed.canonical_url, changed.tiktok_url, changed.x_url) == (
        baseline.canonical_url, baseline.tiktok_url, baseline.x_url
    )
    assert changed.estimated_tiktok_seconds == pytest.approx(
        len(changed.tiktok_script) / 330 * 60
    )
