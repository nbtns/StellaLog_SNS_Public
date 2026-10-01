from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContentBlock:
    type: str
    text: str
    rank: int | None = None
    desc: str | None = None


@dataclass(frozen=True, slots=True)
class Article:
    article_key: str
    concern: str
    gender: str
    mbti: str
    zodiac: str
    title: str
    content: tuple[ContentBlock, ...]
    sns_catchphrase: str
    source_path: Path


@dataclass(frozen=True, slots=True)
class SelectionFilters:
    concern: str | None = None
    mbti: str | None = None
    zodiac: str | None = None
    gender: str | None = None
    include_posted: bool = False


@dataclass(frozen=True, slots=True)
class ArticleLoadResult:
    articles: tuple[Article, ...]
    warnings: tuple[str, ...] = ()
    indexed_count: int = 0


@dataclass(frozen=True, slots=True)
class PostSet:
    article: Article
    selected_at: datetime
    tiktok_script: str
    x_post: str
    canonical_url: str
    tiktok_url: str
    x_url: str
    hashtags: tuple[str, ...]
    tiktok_template_id: str
    x_template_id: str
    source_points: tuple[str, ...]
    estimated_tiktok_seconds: float
    x_weighted_length: int


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    id: int
    article_key: str
    selected_at: datetime
    posted_at: datetime
    category: str
    mbti: str
    zodiac: str
    gender: str
    article_title: str
    source_path: str
    public_url: str
    tiktok_url: str
    x_url: str
    tiktok_script: str
    x_post: str
    hashtags: tuple[str, ...]
    tiktok_template_id: str
    x_template_id: str
    is_posted: bool
    memo: str = ""


@dataclass(slots=True)
class AppSettings:
    data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "sample_data")
    site_origin: str = "https://example.invalid"
    reading_chars_per_minute: int = 330
    voice_engine: str = "voicebox"
    voicebox_url: str = "http://127.0.0.1:17493"
    voicebox_profile_id: str = ""
    voicebox_profile_name: str = "StellaLog Public Demo"
    voice_sample_path: str = ""
    voicevox_url: str = "http://127.0.0.1:50021"
    voicevox_speaker_id: int = 3
    voicevox_speed_scale: float = 1.0
    voicevox_fallback_enabled: bool = True
    weekly_quotas: dict[str, int] = field(
        default_factory=lambda: {
            "personality": 2,
            "ranking": 2,
            "love": 1,
            "work_money": 1,
            "reunion_night": 1,
        }
    )
