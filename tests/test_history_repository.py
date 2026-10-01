from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from stellalog_sns.history_repository import AlreadyPostedError, HistoryRepository
from stellalog_sns.models import Article, PostSet


def make_post_set(
    tmp_path: Path,
    *,
    article_key: str = "personality-intj-aries-all",
    concern: str = "personality",
    gender: str = "all",
    mbti: str = "INTJ",
    zodiac: str = "aries",
    title: str = "INTJ×牡羊座の性格",
) -> PostSet:
    article = Article(
        article_key=article_key,
        concern=concern,
        gender=gender,
        mbti=mbti,
        zodiac=zodiac,
        title=title,
        content=(),
        sns_catchphrase="静かな情熱を持つタイプ？",
        source_path=tmp_path / f"{article_key}.json",
    )
    return PostSet(
        article=article,
        selected_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc),
        tiktok_script="TikTok用の台本です。",
        x_post="X用の投稿です。",
        canonical_url=f"https://n-stellalog.com/reading/{mbti.lower()}/{zodiac}/{gender}/{concern}",
        tiktok_url="https://n-stellalog.com/example?utm_source=tiktok",
        x_url="https://n-stellalog.com/example?utm_source=x",
        hashtags=("#MBTI", "#星座"),
        tiktok_template_id="tiktok-1",
        x_template_id="x-1",
        source_points=("特徴1", "特徴2"),
        estimated_tiktok_seconds=65,
        x_weighted_length=120,
    )


def test_mark_posted_saves_complete_record(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    post_set = make_post_set(tmp_path)
    posted_at = datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc)

    record = repository.mark_posted(post_set, posted_at=posted_at, memo="初回投稿")

    assert record.id > 0
    assert record.article_key == post_set.article.article_key
    assert record.posted_at == posted_at
    assert record.category == "personality"
    assert record.public_url == post_set.canonical_url
    assert record.hashtags == ("#MBTI", "#星座")
    assert record.is_posted is True
    assert record.memo == "初回投稿"
    assert repository.is_posted(post_set.article.article_key)


def test_candidate_is_not_saved_until_mark_posted_is_called(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    make_post_set(tmp_path)

    assert repository.list_records() == []


def test_duplicate_active_post_is_rejected(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    post_set = make_post_set(tmp_path)
    repository.mark_posted(post_set)

    with pytest.raises(AlreadyPostedError):
        repository.mark_posted(post_set)


def test_unmark_keeps_history_and_allows_reposting(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    post_set = make_post_set(tmp_path)
    first = repository.mark_posted(post_set)

    assert repository.unmark_posted(first.id)
    assert not repository.is_posted(post_set.article.article_key)
    assert repository.get(first.id).is_posted is False

    second = repository.mark_posted(post_set)
    assert second.id != first.id
    assert repository.is_posted(post_set.article.article_key)


def test_search_filters_and_memo_update(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    personality = repository.mark_posted(
        make_post_set(tmp_path),
        posted_at=datetime(2026, 9, 1, 8, 0),
    )
    repository.mark_posted(
        make_post_set(
            tmp_path,
            article_key="love-enfp-taurus-female",
            concern="love",
            gender="female",
            mbti="ENFP",
            zodiac="taurus",
            title="ENFP×牡牛座女性の恋愛",
        ),
        posted_at=datetime(2026, 9, 2, 8, 0),
    )

    assert repository.update_memo(personality.id, "反応が良かった")
    assert [item.id for item in repository.list_records(query="反応")] == [personality.id]
    assert len(repository.list_records(category="love", gender="female")) == 1
    assert len(repository.list_records(mbti="INTJ", zodiac="aries")) == 1
    assert len(repository.list_records(date_from=date(2026, 9, 2))) == 1
    assert len(repository.list_records(date_to=date(2026, 9, 1))) == 1
    assert repository.posted_article_keys() == {
        "personality-intj-aries-all",
        "love-enfp-taurus-female",
    }


def test_corrupt_database_is_preserved_and_recreated(tmp_path: Path) -> None:
    database_path = tmp_path / "history.sqlite3"
    tmp_path.mkdir(parents=True, exist_ok=True)
    database_path.write_bytes(b"this is not sqlite")

    repository = HistoryRepository(tmp_path)

    assert repository.list_records() == []
    assert database_path.exists()
    recovered = list((tmp_path / "recovery").glob("history-corrupt-*.sqlite3"))
    assert len(recovered) == 1
    assert recovered[0].read_bytes() == b"this is not sqlite"


def test_date_to_string_includes_the_whole_day(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    post_set = make_post_set(tmp_path)
    repository.mark_posted(
        post_set,
        posted_at=datetime(2026, 9, 1, 21, 30),
    )

    records = repository.list_records(date_to="2026-09-01")

    assert len(records) == 1
