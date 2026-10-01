from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from stellalog_sns.article_repository import ArticleRepository
from stellalog_sns.generator import PostGenerator
from stellalog_sns.x_thread import split_x_thread


SAMPLE_DATA = (
    Path(__file__).parents[1]
    / "src"
    / "stellalog_sns"
    / "sample_data"
)
PUBLIC_ORIGIN = "https://example.invalid"
EXPECTED_CONCERNS = {
    "personality",
    "ranking",
    "love",
    "work",
    "money",
    "reunion",
    "night",
}


def test_public_sample_articles_load_and_generate_safe_urls() -> None:
    loaded = ArticleRepository(SAMPLE_DATA).load_all()

    assert loaded.warnings == ()
    assert loaded.indexed_count == 7
    assert len(loaded.articles) == 7
    assert {article.concern for article in loaded.articles} == EXPECTED_CONCERNS

    generator = PostGenerator()
    posts = {
        article.concern: generator.generate(
            article,
            PUBLIC_ORIGIN,
            selected_at=datetime(2026, 10, 1, 12),
        )
        for article in loaded.articles
    }

    assert set(posts) == EXPECTED_CONCERNS
    for post in posts.values():
        assert {
            urlparse(post.canonical_url).hostname,
            urlparse(post.tiktok_url).hostname,
            urlparse(post.x_url).hostname,
        } == {"example.invalid"}
        assert "example.invalid" in post.canonical_url

    for concern in EXPECTED_CONCERNS - {"ranking"}:
        assert 60 <= posts[concern].estimated_tiktok_seconds <= 75


def test_demo_ranking_keeps_first_place_and_reason_together() -> None:
    loaded = ArticleRepository(SAMPLE_DATA).load_all()
    ranking_article = next(article for article in loaded.articles if article.concern == "ranking")
    post = PostGenerator().generate(
        ranking_article,
        PUBLIC_ORIGIN,
        selected_at=datetime(2026, 10, 1, 12),
    )

    tiktok = post.tiktok_script.replace("\n", "")
    best, worst = tiktok.split("地雷相性1位は", 1)
    assert "神相性1位はISTJ牡牛座" in best
    assert "約束を守る相手" in best
    assert "計画を実行に移しやすく" in best
    assert worst.startswith("INTP水瓶座")
    assert "すぐに答えを求めると距離が広がる" in worst
    assert "相手のペースも聞く" in worst

    x_first, x_second = split_x_thread(post.x_post)
    assert "【神相性1位：ISTJ×牡牛座】" in x_first
    assert "約束を守る相手" in x_first
    assert "【地雷相性1位：INTP×水瓶座】" in x_second
    assert "すぐに答えを求めると距離が広がる" in x_second
    assert x_second.endswith(post.x_url)
