"""UI とローカル処理をつなぐアプリケーションコントローラー。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .article_repository import ArticleRepository
from .draft_repository import DraftRepository
from .generator import PostGenerator
from .history_repository import HistoryRepository
from .media_service import GeneratedMedia, GeneratedVoicePreview, GeneratedVoiceCardPreview, MediaService
from .models import AppSettings, Article, HistoryRecord, PostSet, SelectionFilters
from .selector import ArticleSelector
from .settings import SettingsStore
from .voice_services import VoiceProfile


class StudioController:
    """画面に保存処理や記事読み込みの詳細を漏らさないための窓口。"""

    def __init__(
        self,
        settings_store: SettingsStore | None = None,
        history_repository: HistoryRepository | None = None,
    ) -> None:
        self.settings_store = settings_store or SettingsStore()
        self.draft_repository = DraftRepository(self.settings_store.app_dir)
        self.history_repository = history_repository or HistoryRepository()
        self.settings = self.settings_store.load()
        self.articles: list[Article] = []
        self.load_warnings: tuple[str, ...] = ()
        self.current_post: PostSet | None = None
        self._session_seen: set[str] = set()
        self.reload_articles()

    def reload_articles(self) -> int:
        """設定中の記事フォルダから、常に最新の記事を読み直す。"""

        data_dir = Path(self.settings.data_dir)
        result = ArticleRepository(data_dir).load_all()
        self.articles = list(result.articles)
        self.load_warnings = tuple(result.warnings)
        self.current_post = None
        self._session_seen.clear()
        return len(self.articles)

    def save_settings(self, settings: AppSettings) -> int:
        self.settings_store.save(settings)
        self.settings = settings
        return self.reload_articles()

    def create_post(self, filters: SelectionFilters) -> PostSet:
        """候補を選び、投稿セットを生成する。ここでは履歴へ保存しない。"""

        history = self.history_repository.list_records()
        article = ArticleSelector(self.settings.weekly_quotas).choose(
            self.articles,
            filters,
            history,
            self._session_seen,
            datetime.now(),
        )
        self._session_seen.add(article.article_key)
        recent_template_ids: list[str] = []
        for record in history[:12]:
            recent_template_ids.extend(
                (record.tiktok_template_id, record.x_template_id)
            )
        self.current_post = PostGenerator().generate(
            article,
            self.settings.site_origin,
            recent_template_ids=tuple(recent_template_ids),
            selected_at=datetime.now(),
            reading_cpm=round(
                self.settings.reading_chars_per_minute
                * (
                    self.settings.voicevox_speed_scale
                    if self.settings.voice_engine == "voicevox"
                    else 1.0
                )
            ),
        )
        return self.current_post

    def change_candidate(self, filters: SelectionFilters) -> PostSet:
        return self.create_post(filters)

    def mark_current_posted(self, memo: str = "") -> HistoryRecord:
        if self.current_post is None:
            raise RuntimeError("先に「今日の投稿を作る」を押してください。")
        return self.history_repository.mark_posted(self.current_post, memo=memo)

    def history(self, **filters: object) -> list[HistoryRecord]:
        return self.history_repository.list_records(**filters)

    def build_chatgpt_prompt(self) -> str:
        if self.current_post is None:
            return ""
        return PostGenerator.build_chatgpt_prompt(self.current_post)

    def register_voice_sample(
        self,
        sample_path: Path | str,
        reference_text: str,
    ) -> VoiceProfile:
        """録音をVoiceboxへ登録し、次回起動後も使えるよう設定へ保存する。"""

        sample_settings = replace(
            self.settings,
            voice_sample_path=str(Path(sample_path).resolve()),
        )
        self.settings_store.save(sample_settings)
        self.settings = sample_settings
        profile = MediaService(sample_settings).register_voice_sample(
            sample_path,
            reference_text,
        )
        updated = replace(
            sample_settings,
            voicebox_profile_id=profile.id,
        )
        self.settings_store.save(updated)
        self.settings = updated
        return profile

    def generate_current_video(
        self,
        progress: Callable[[int, str], None] | None = None,
        *,
        narration_script: str | None = None,
        voice_preview: GeneratedVoicePreview | None = None,
    ) -> GeneratedMedia:
        """現在表示中の投稿セットから完成動画を作る。"""

        if self.current_post is None:
            raise RuntimeError("先に「今日の投稿を作る」を押してください。")
        return MediaService(self.settings, voicevox_cache_dir=self.settings_store.app_dir / "voicevox_cache").generate_video(
            self.current_post,
            narration_script=narration_script,
            voice_preview=voice_preview,
            progress=progress,
        )

    def generate_current_voice_preview(
        self,
        progress: Callable[[int, str], None] | None = None,
        *,
        narration_script: str | None = None,
    ) -> GeneratedVoicePreview:
        """現在の音声用の読みからVOICEVOX確認音声を作る。"""

        if self.current_post is None:
            raise RuntimeError("先に「今日の投稿を作る」を押してください。")
        return MediaService(self.settings, voicevox_cache_dir=self.settings_store.app_dir / "voicevox_cache").generate_voicevox_preview(
            self.current_post,
            narration_script=narration_script,
            progress=progress,
        )

    def generate_current_voice_card_preview(
        self, card_index: int, progress: Callable[[int, str], None] | None = None,
        *, narration_script: str | None = None,
    ) -> GeneratedVoiceCardPreview:
        if self.current_post is None:
            raise RuntimeError("先に「今日の投稿を作る」を押してください。")
        return MediaService(
            self.settings, voicevox_cache_dir=self.settings_store.app_dir / "voicevox_cache"
        ).generate_voicevox_card_preview(
            self.current_post, card_index, narration_script=narration_script, progress=progress
        )
