from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from stellalog_sns import generator, ranking_posts
from stellalog_sns.models import Article, ContentBlock
from stellalog_sns.labels import MBTI_VALUES, ZODIAC_LABELS
from stellalog_sns.ranking_pilot import _ranking_source_points, build_ranking_pilot
from stellalog_sns.url_builder import x_weighted_length
from stellalog_sns.x_thread import split_x_thread


@pytest.fixture
def reviewed_article(monkeypatch: pytest.MonkeyPatch) -> Article:
    path = Path(__file__).parent / "fixtures" / "infj_cancer_ranking.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    article = Article(
        article_key="ranking/unisex/infj/aries",
        concern="ranking", gender="unisex", mbti="infj", zodiac="aries",
        title=payload["title"], sns_catchphrase=payload["sns_catchphrase"],
        source_path=path,
        content=tuple(ContentBlock(**block) for block in payload["content"]),
    )
    signature = hashlib.sha256(json.dumps(
        _ranking_source_points(article), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    entry = {
        "source_sha256": signature,
        "hook": "世界が広がる恋と\n尽くすほど離れていく恋",
        "best": [
            "相手の気持ちを気遣って自分を後回しにするあなたを、世話役から解放してくれます。",
            "新しい場所や知らない体験へ連れ出してくれるので、一緒にいると世界が広がります。",
            "楽しいだけではなく深い話にも応えてくれるため、表面的な付き合いにとどまりません。",
        ],
        "worst": [
            "深い絆を確かめたいあなたに対して、相手は今この瞬間の自由を求める傾向があります。",
            "相手を思って尽くすほど重いと受け取られやすく、かえって距離が開いてしまいます。",
            "相手が離れるほどあなたの執着が強まりやすく、お互いのすれ違いが続きやすくなります。",
        ],
    }
    monkeypatch.setattr(ranking_posts, "_load_reviewed_copy", lambda: {article.article_key: entry})
    return article


def test_ranking_structure_separates_love_first_places_and_their_reasons(reviewed_article: Article) -> None:
    post = generator.PostGenerator().generate(reviewed_article, "https://n-stellalog.com")
    good, bad = post.tiktok_script.replace("\n", "").split("地雷相性1位は", 1)
    assert "INFJ牡羊座の恋愛相性" in good
    assert "神相性1位はENTP射手座" in good
    assert "世話役から解放" in good
    assert "新しい場所" in good
    assert "深い話" in good
    assert bad.startswith("ESTP牡羊座")
    assert "今この瞬間の自由" in bad
    assert "重いと受け取られ" in bad
    assert "執着が強まり" in bad
    assert "StellaLog独自" not in good + bad
    assert "ENFJ獅子座" not in good + bad
    assert "4位" not in good + bad
    assert "×" not in good + bad
    assert post.source_points == _ranking_source_points(reviewed_article)


def test_x_keeps_complete_reasons_and_correct_partner_in_each_post(reviewed_article: Article) -> None:
    post = generator.PostGenerator().generate(reviewed_article, "https://n-stellalog.com")
    first, second = split_x_thread(post.x_post)
    assert "【神相性1位：ENTP×射手座】" in first
    assert "【地雷相性1位：ESTP×牡羊座】" in second
    assert "世話役から解放" in first and "新しい場所" in first
    assert "今この瞬間の自由" in second and "重いと受け取られ" in second
    assert "地雷相性" not in first and "神相性" not in second
    assert "StellaLog独自" not in post.x_post
    assert all(x_weighted_length(part) <= 280 for part in (first, second))
    assert second.endswith(post.x_url)
    assert all(part.split("\n\n")[-2].endswith("。") for part in (first, second))


def test_missing_love_section_never_uses_friend_or_work_rank_one(reviewed_article: Article) -> None:
    changed = replace(reviewed_article, content=tuple(
        replace(block, text=block.text.replace("恋愛", "別分野"))
        if block.type in {"h3", "h4"} and "地雷相性" in block.text else block
        for block in reviewed_article.content
    ))
    with pytest.raises(ValueError, match="恋愛の地雷相性1位と理由"):
        generator.PostGenerator().generate(changed, "https://n-stellalog.com")


def test_updated_reason_requires_review(reviewed_article: Article) -> None:
    source_reason = _ranking_source_points(reviewed_article)[1]
    changed = replace(reviewed_article, content=tuple(
        replace(block, text="理由が更新されました。") if block.text == source_reason else block
        for block in reviewed_article.content
    ))
    with pytest.raises(ValueError, match="更新されています"):
        generator.PostGenerator().generate(changed, "https://n-stellalog.com")


def test_missing_reviewed_copy_never_falls_back_to_old_ranking(
    reviewed_article: Article, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking_posts, "_load_reviewed_copy", lambda: {})
    with pytest.raises(ValueError, match="未確認"):
        generator.PostGenerator().generate(reviewed_article, "https://n-stellalog.com")


def test_changes_outside_two_first_places_do_not_change_generated_posts(reviewed_article: Article) -> None:
    source = generator.PostGenerator().generate(reviewed_article, "https://n-stellalog.com")
    changed = replace(reviewed_article, content=tuple(
        replace(block, desc="4位の別の説明です。")
        if block.type == "ranking" and block.rank == 4 else block
        for block in reviewed_article.content
    ))
    actual = generator.PostGenerator().generate(changed, "https://n-stellalog.com")
    assert actual.tiktok_script == source.tiktok_script
    assert actual.x_post == source.x_post


def test_reviewed_pilot_remains_exactly_the_accepted_copy(reviewed_article: Article) -> None:
    pilot_article = replace(
        reviewed_article, article_key="ranking/unisex/infj/cancer", zodiac="cancer"
    )
    actual = ranking_posts.build_ranking_posts(
        pilot_article, "https://example.com/article",
        format_tiktok=lambda _: pytest.fail("承認済み字幕の改行は変更しない"),
    )
    assert actual == build_ranking_pilot(pilot_article, "https://example.com/article")
