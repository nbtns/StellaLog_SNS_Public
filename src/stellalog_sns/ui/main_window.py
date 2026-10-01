"""StellaLog SNS Studio のメイン画面。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..controller import StudioController
from ..draft_repository import Draft
from ..history_repository import AlreadyPostedError
from ..labels import (
    CATEGORY_LABELS,
    GENDER_LABELS,
    MBTI_VALUES,
    ZODIAC_LABELS,
    format_mbti_zodiac,
)
from ..media_service import GeneratedMedia, GeneratedVoicePreview, GeneratedVoiceCardPreview
from ..models import PostSet, SelectionFilters
from ..paths import generated_videos_dir, voice_samples_dir
from ..pronunciation import correct_pronunciation
from ..url_builder import x_weighted_length
from ..voice_services import VoiceProfile
from ..x_thread import split_x_thread
from .background_task import BackgroundTask
from .draft_dialog import DraftDialog
from .history_dialog import HistoryDialog
from .settings_dialog import SettingsDialog
from .subtitle_editor import SubtitleEditor
from .voice_recording_dialog import VoiceRecordingDialog


def combo_value(combo: QComboBox) -> str | None:
    return combo.currentData()


class MainWindow(QMainWindow):
    def __init__(self, controller: StudioController | None = None) -> None:
        super().__init__()
        self.controller = controller or StudioController()
        self._post: PostSet | None = None
        self._last_video_path: Path | None = None
        self._background_task: BackgroundTask | None = None
        self._background_error_title = "処理を完了できませんでした"
        self._updating_narration_text = False
        self._narration_manually_edited = False
        self._voice_preview: GeneratedVoicePreview | None = None
        self._loading_post = False
        self._draft_completed = False
        self._syncing_cards = False
        self._playing_card_preview = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(800)
        self._draft_timer.timeout.connect(self._save_draft)
        self._preview_audio_output = QAudioOutput(self)
        self._preview_audio_output.setVolume(1.0)
        self._preview_player = QMediaPlayer(self)
        self._preview_player.setAudioOutput(self._preview_audio_output)
        self._preview_player.playbackStateChanged.connect(
            self._voice_preview_state_changed
        )
        self._preview_player.errorOccurred.connect(
            self._show_voice_preview_playback_error
        )
        self._media_elapsed_seconds = 0
        self._media_timer = QTimer(self)
        self._media_timer.setInterval(1_000)
        self._media_timer.timeout.connect(self._update_media_elapsed)
        self.setWindowTitle("StellaLog SNS Studio — 公開デモ版")
        self.resize(1080, 780)
        self.setMinimumSize(860, 650)
        self._build_ui()
        self._set_post_actions_enabled(False)
        self._show_load_status()
        self._show_draft_availability()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("StellaLog SNS Studio  公開デモ版")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        self.drafts_button = QPushButton("下書きから再開")
        header.addWidget(self.drafts_button)
        self.history_button = QPushButton("投稿履歴を見る")
        self.settings_button = QPushButton("設定")
        header.addWidget(self.history_button)
        header.addWidget(self.settings_button)
        outer.addLayout(header)

        lead = QLabel("公開デモ版です。同梱の架空記事で台本・字幕編集を試せます。記事URLはデモ用で、実際の記事にはつながりません。")
        self.lead_label = lead
        lead.setWordWrap(True)
        lead.setStyleSheet("color: #505766;")
        outer.addWidget(lead)

        filters = QGroupBox("選定条件")
        self.filters_box = filters
        filter_layout = QHBoxLayout(filters)
        self.category_combo = self._combo(CATEGORY_LABELS)
        self.mbti_combo = self._combo({value: value.upper() for value in MBTI_VALUES})
        self.zodiac_combo = self._combo(ZODIAC_LABELS)
        self.gender_combo = self._combo(GENDER_LABELS)
        for label, widget in (
            ("カテゴリー", self.category_combo),
            ("MBTI", self.mbti_combo),
            ("星座", self.zodiac_combo),
            ("性別", self.gender_combo),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(widget)
            filter_layout.addLayout(column)
        self.include_posted = QCheckBox("投稿済みの記事も含める")
        self.include_posted.setToolTip("通常はオフのまま使うと、同じ記事の重複を防げます。")
        filter_layout.addWidget(self.include_posted, alignment=Qt.AlignmentFlag.AlignBottom)
        outer.addWidget(filters)

        action_row = QHBoxLayout()
        self.create_button = QPushButton("今日の投稿を作る")
        self.create_button.setMinimumHeight(42)
        self.create_button.setStyleSheet(
            "QPushButton { background:#356ae6; color:white; font-weight:700; padding:8px 22px; border-radius:6px; }"
            "QPushButton:hover { background:#2859c7; }"
        )
        self.change_button = QPushButton("別の候補にする")
        self.save_draft_button = QPushButton("下書きを保存")
        self.posted_button = QPushButton("投稿済みにする")
        self.posted_button.setStyleSheet("font-weight: 700;")
        action_row.addWidget(self.create_button)
        action_row.addWidget(self.change_button)
        action_row.addWidget(self.save_draft_button)
        action_row.addStretch()
        action_row.addWidget(self.posted_button)
        outer.addLayout(action_row)

        media_box = QGroupBox("TikTok動画")
        media_layout = QVBoxLayout(media_box)
        media_actions = QHBoxLayout()
        self.voice_button = QPushButton("自分の声を登録")
        self.voice_preview_button = QPushButton("① VOICEVOX音声を確認")
        self.voice_preview_button.setToolTip(
            "先に確認音声を作って聞くと、「② 動画を作る」を押せるようになります。"
        )
        self.video_button = QPushButton("② 動画を作る")
        self.video_button.setStyleSheet(
            "QPushButton { background:#6f3cc3; color:white; font-weight:700; padding:7px 18px; border-radius:6px; }"
            "QPushButton:hover { background:#5930a1; }"
        )
        self.open_video_button = QPushButton("完成動画を開く")
        self.open_video_folder_button = QPushButton("保存フォルダを開く")
        self.voice_status_label = QLabel()
        self.voice_status_label.setWordWrap(True)
        media_actions.addWidget(self.voice_button)
        media_actions.addWidget(self.voice_preview_button)
        media_actions.addWidget(self.video_button)
        media_actions.addWidget(self.open_video_button)
        media_actions.addWidget(self.open_video_folder_button)
        media_actions.addWidget(self.voice_status_label, 1)
        media_layout.addLayout(media_actions)
        progress_row = QHBoxLayout()
        self.media_progress_bar = QProgressBar()
        self.media_progress_bar.setRange(0, 100)
        self.media_progress_bar.setValue(0)
        self.media_progress_bar.setTextVisible(True)
        self.media_progress_bar.setVisible(False)
        self.media_progress_label = QLabel()
        self.media_progress_label.setWordWrap(True)
        self.media_progress_label.setVisible(False)
        self.media_elapsed_label = QLabel("経過 00:00")
        self.media_elapsed_label.setMinimumWidth(82)
        self.media_elapsed_label.setVisible(False)
        progress_row.addWidget(self.media_progress_bar, 2)
        progress_row.addWidget(self.media_progress_label, 3)
        progress_row.addWidget(self.media_elapsed_label)
        media_layout.addLayout(progress_row)
        outer.addWidget(media_box)

        info = QFrame()
        self.article_info_box = info
        info.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(info)
        self.category_label = QLabel("—")
        self.type_label = QLabel("—")
        self.gender_label = QLabel("—")
        self.article_title = QLabel("まだ記事は選ばれていません")
        self.article_title.setWordWrap(True)
        self.article_title.setStyleSheet("font-size: 17px; font-weight: 700;")
        self.catchphrase_label = QLabel("「今日の投稿を作る」を押してください。")
        self.catchphrase_label.setWordWrap(True)
        grid.addWidget(QLabel("カテゴリー"), 0, 0)
        grid.addWidget(self.category_label, 0, 1)
        grid.addWidget(QLabel("MBTI・星座"), 0, 2)
        grid.addWidget(self.type_label, 0, 3)
        grid.addWidget(QLabel("性別"), 0, 4)
        grid.addWidget(self.gender_label, 0, 5)
        grid.addWidget(self.article_title, 1, 0, 1, 6)
        grid.addWidget(self.catchphrase_label, 2, 0, 1, 6)
        outer.addWidget(info)

        self.tabs = QTabWidget()
        self.tiktok_text = self._tiktok_text_tab()
        self.narration_text_edit = self._narration_text_tab()
        self.x_text = self._text_tab("X投稿文（2投稿）")
        self.chatgpt_text = self._text_tab("ChatGPT用プロンプト")
        self.subtitle_editor = SubtitleEditor()
        self.tabs.addTab(self.subtitle_editor, "字幕を見ながら編集")
        self.subtitle_editor.scriptsChanged.connect(self._card_scripts_edited)
        self.subtitle_editor.previewRequested.connect(self._preview_voice_card)
        self.subtitle_editor.subtitle_edit.textChanged.connect(self._pending_card_input_changed)
        self.subtitle_editor.narration_edit.textChanged.connect(self._pending_card_input_changed)
        self.tabs.currentChanged.connect(self._tab_changed)
        outer.addWidget(self.tabs, stretch=1)
        self.draft_status_label = QLabel("編集中の台本と音声用の読みは自動保存されます。")
        self.draft_status_label.setStyleSheet("color: #505766;")
        outer.addWidget(self.draft_status_label)

        self.meta_widget = QWidget()
        meta = QGridLayout(self.meta_widget)
        meta.setContentsMargins(0, 0, 0, 0)
        self.tiktok_stats = QLabel("読み上げ時間: —")
        self.x_stats = QLabel("X文字数: —")
        self.hashtags_label = QLabel("ハッシュタグ: —")
        self.hashtags_label.setWordWrap(True)
        self.tiktok_url_label = QLabel("TikTok用記事URL: —")
        self.tiktok_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tiktok_url_label.setWordWrap(True)
        self.x_url_label = QLabel("X投稿内の計測用記事URL: —")
        self.x_url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.x_url_label.setWordWrap(True)
        meta.addWidget(self.tiktok_stats, 0, 0)
        meta.addWidget(self.x_stats, 0, 1)
        meta.addWidget(self.hashtags_label, 1, 0, 1, 2)
        meta.addWidget(self.tiktok_url_label, 2, 0, 1, 2)
        meta.addWidget(self.x_url_label, 3, 0, 1, 2)
        outer.addWidget(self.meta_widget)

        copies = QHBoxLayout()
        self.copy_x_first_button = QPushButton("X 1つ目をコピー")
        self.copy_x_second_button = QPushButton("X 2つ目をコピー")
        self.copy_script_button = QPushButton("動画台本をコピー")
        self.copy_url_button = QPushButton("記事URLをコピー")
        self.copy_prompt_button = QPushButton("ChatGPT用プロンプトをコピー")
        for button in (
            self.copy_x_first_button,
            self.copy_x_second_button,
            self.copy_script_button,
            self.copy_url_button,
            self.copy_prompt_button,
        ):
            copies.addWidget(button)
        outer.addLayout(copies)

        self.status_label = QLabel("準備中…")
        self.status_label.setStyleSheet("color: #505766;")
        outer.addWidget(self.status_label)

        self.create_button.clicked.connect(self._create_post)
        self.change_button.clicked.connect(self._create_post)
        self.posted_button.clicked.connect(self._mark_posted)
        self.history_button.clicked.connect(self._open_history)
        self.drafts_button.clicked.connect(self._open_drafts)
        self.save_draft_button.clicked.connect(lambda: self._save_draft())
        self.settings_button.clicked.connect(self._open_settings)
        self.copy_x_first_button.clicked.connect(lambda: self._copy_x_part(0))
        self.copy_x_second_button.clicked.connect(lambda: self._copy_x_part(1))
        self.copy_script_button.clicked.connect(lambda: self._copy(self.tiktok_text.toPlainText(), "動画台本"))
        self.copy_url_button.clicked.connect(self._copy_article_url)
        self.copy_prompt_button.clicked.connect(lambda: self._copy(self.chatgpt_text.toPlainText(), "ChatGPT用プロンプト"))
        self.voice_button.clicked.connect(self._record_voice)
        self.voice_preview_button.clicked.connect(self._preview_voice)
        self.video_button.clicked.connect(self._generate_video)
        self.open_video_button.clicked.connect(self._open_last_video)
        self.open_video_folder_button.clicked.connect(self._open_video_folder)
        self.tiktok_text.textChanged.connect(self._tiktok_script_edited)
        self.narration_text_edit.textChanged.connect(self._narration_text_edited)
        self.open_video_button.setEnabled(False)
        self._update_voice_status()

    def _combo(self, values: dict[str, str]) -> QComboBox:
        combo = QComboBox()
        combo.addItem("すべて", None)
        for value, label in values.items():
            combo.addItem(label, value)
        combo.setMinimumWidth(120)
        return combo

    def _text_tab(self, title: str) -> QTextEdit:
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlaceholderText("投稿セットを作ると、ここに文章が表示されます。")
        self.tabs.addTab(text, title)
        return text

    def _tiktok_text_tab(self) -> QTextEdit:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.tiktok_edit_help = QLabel(
            "台本はこの画面で編集できます。通常の改行は同じ字幕内、空白行で次の字幕へ切り替わります。"
            "「、」を入れると音声だけをそこで区切り、字幕には表示しません。"
            "読み間違えやすい語句も、字幕を変えず音声だけ自動補正します。"
        )
        self.tiktok_edit_help.setWordWrap(True)
        self.tiktok_edit_help.setStyleSheet("color: #505766;")
        text = QTextEdit()
        text.setPlaceholderText("投稿セットを作ると、ここに編集できる台本が表示されます。")
        layout.addWidget(self.tiktok_edit_help)
        layout.addWidget(text, 1)
        self.tabs.addTab(page, "TikTok動画台本")
        return text

    def _narration_text_tab(self) -> QTextEdit:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        help_label = QLabel(
            "VOICEVOXが間違える漢字だけ、読ませたいひらがな・カタカナへ直してください。"
            "ここを直しても動画の字幕は変わりません。空白行の位置はTikTok台本と同じままにします。"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #505766;")
        action_row = QHBoxLayout()
        self.narration_status_label = QLabel("投稿セットを作ると、自動補正した読みが表示されます。")
        self.narration_status_label.setWordWrap(True)
        self.reset_narration_button = QPushButton("台本から読みを作り直す")
        self.reset_narration_button.clicked.connect(self._reset_narration_from_script)
        action_row.addWidget(self.narration_status_label, 1)
        action_row.addWidget(self.reset_narration_button)
        text = QTextEdit()
        text.setPlaceholderText("投稿セットを作ると、ここに編集できる音声用の読みが表示されます。")
        layout.addWidget(help_label)
        layout.addLayout(action_row)
        layout.addWidget(text, 1)
        self.tabs.addTab(page, "音声用の読み")
        return text

    def _set_narration_text(self, text: str, *, status: str) -> None:
        self._invalidate_voice_preview()
        self._updating_narration_text = True
        try:
            self.narration_text_edit.setPlainText(text)
        finally:
            self._updating_narration_text = False
        self._narration_manually_edited = False
        self.narration_status_label.setText(status)
        self._sync_subtitle_editor()
        self._schedule_draft()

    def _sync_subtitle_editor(self) -> None:
        if self._syncing_cards or not hasattr(self, "subtitle_editor"):
            return
        self.subtitle_editor.set_scripts(self.tiktok_text.toPlainText(), self.narration_text_edit.toPlainText())

    def _card_scripts_edited(self, subtitle: str, narration: str) -> None:
        narration_was_edited = self.narration_text_edit.toPlainText() != narration
        self._syncing_cards = True
        try:
            if self.tiktok_text.toPlainText() != subtitle:
                self.tiktok_text.setPlainText(subtitle)
            if narration_was_edited and self.narration_text_edit.toPlainText() != narration:
                self.narration_text_edit.setPlainText(narration)
        finally:
            self._syncing_cards = False
        self._sync_subtitle_editor()
        self._schedule_draft()

    def _pending_card_input_changed(self) -> None:
        if not self._loading_post and self.subtitle_editor.has_pending_edits():
            self._invalidate_voice_preview()
            self._schedule_draft()

    def _apply_pending_card_edits(self) -> None:
        if self.subtitle_editor.has_pending_edits():
            self._card_scripts_edited(*self.subtitle_editor.pending_scripts())

    def _tab_changed(self, _index: int) -> None:
        editing_cards = self.tabs.currentWidget() is self.subtitle_editor
        self.lead_label.setText(
            "字幕を見ながら編集しています。記事の選定条件やURLは「TikTok動画台本」タブで確認できます。"
            if editing_cards else
            "公開デモ版です。同梱の架空記事で台本・字幕編集を試せます。記事URLはデモ用で、実際の記事にはつながりません。"
        )
        self.filters_box.setVisible(not editing_cards)
        self.article_info_box.setVisible(not editing_cards)
        if hasattr(self, "meta_widget"):
            self.meta_widget.setVisible(not editing_cards)
        if not editing_cards:
            self._apply_pending_card_edits()

    def _reset_narration_from_script(self) -> None:
        script = self.tiktok_text.toPlainText()
        self._set_narration_text(
            correct_pronunciation(script),
            status="TikTok台本から音声用の読みを作り直しました。",
        )

    def _narration_text_edited(self) -> None:
        if self._updating_narration_text:
            return
        self._invalidate_voice_preview()
        self._narration_manually_edited = True
        self.narration_status_label.setText(
            "手動で直した読みを動画に使います。字幕の表記は変わりません。"
        )
        self._schedule_draft()
        self._sync_subtitle_editor()

    def _tiktok_script_edited(self) -> None:
        if self._post is None:
            return
        script = self.tiktok_text.toPlainText()
        if script == self._post.tiktok_script:
            return
        settings = self.controller.settings
        speed_scale = (
            settings.voicevox_speed_scale
            if settings.voice_engine == "voicevox"
            else 1.0
        )
        estimated_seconds = (
            len(script) / (settings.reading_chars_per_minute * speed_scale) * 60
        )
        self._post = replace(
            self._post,
            tiktok_script=script,
            estimated_tiktok_seconds=estimated_seconds,
        )
        self.controller.current_post = self._post
        self.tiktok_stats.setText(f"読み上げ時間: 約{round(estimated_seconds)}秒")
        self._invalidate_voice_preview()
        if self._narration_manually_edited:
            self.narration_status_label.setText(
                "TikTok台本を変更しました。手動で直した音声用の読みも確認してください。"
            )
        else:
            self._set_narration_text(
                correct_pronunciation(script),
                status="TikTok台本の変更に合わせて、音声用の読みも更新しました。",
            )
        self._schedule_draft()
        self._sync_subtitle_editor()

    def _filters(self) -> SelectionFilters:
        return SelectionFilters(
            concern=combo_value(self.category_combo),
            mbti=combo_value(self.mbti_combo),
            zodiac=combo_value(self.zodiac_combo),
            gender=combo_value(self.gender_combo),
            include_posted=self.include_posted.isChecked(),
        )

    def _create_post(self) -> None:
        if not self._save_draft():
            return
        self.create_button.setEnabled(False)
        self.change_button.setEnabled(False)
        self.status_label.setText("記事を選び、投稿文を作っています…")
        try:
            post = self.controller.create_post(self._filters())
        except Exception as exc:
            self._show_error("投稿セットを作れませんでした", exc)
            return
        finally:
            self.create_button.setEnabled(True)
            self.change_button.setEnabled(True)
        self._display_post(post)
        self.status_label.setText("投稿セットを作成しました。内容を確認してから手動で投稿してください。")

    def _display_post(self, post: PostSet) -> None:
        self._loading_post = True
        self._draft_completed = False
        self._post = post
        self.controller.current_post = post
        self._last_video_path = None
        self.open_video_button.setEnabled(False)
        article = post.article
        self.category_label.setText(CATEGORY_LABELS.get(article.concern, article.concern))
        self.type_label.setText(format_mbti_zodiac(article.mbti, article.zodiac))
        self.gender_label.setText(GENDER_LABELS.get(article.gender, article.gender))
        self.article_title.setText(article.title)
        self.catchphrase_label.setText(article.sns_catchphrase or "SNS用キャッチコピーなし")
        self.tiktok_text.setPlainText(post.tiktok_script)
        self._set_narration_text(
            correct_pronunciation(post.tiktok_script),
            status="自動補正した読みです。必要な漢字だけ、読ませたい表記へ直せます。",
        )
        self.x_text.setPlainText(post.x_post)
        try:
            prompt = self.controller.build_chatgpt_prompt()
        except Exception as exc:
            prompt = f"プロンプトを作成できませんでした: {exc}"
        self.chatgpt_text.setPlainText(prompt)
        self.tiktok_stats.setText(
            f"読み上げ時間: 約{round(post.estimated_tiktok_seconds)}秒"
        )
        first_x, second_x = split_x_thread(post.x_post)
        first_weight = x_weighted_length(first_x)
        second_weight = x_weighted_length(second_x)
        self.x_stats.setText(
            "X文字数: "
            f"1つ目 {first_weight} / 280（日本語約{(first_weight + 1) // 2} / 140字相当）、"
            f"2つ目 {second_weight} / 280（日本語約{(second_weight + 1) // 2} / 140字相当）"
        )
        hashtags = " ".join(post.hashtags) if not isinstance(post.hashtags, str) else post.hashtags
        self.hashtags_label.setText(f"ハッシュタグ: {hashtags or 'なし'}")
        self.tiktok_url_label.setText(f"TikTok用記事URL: {post.tiktok_url}")
        self.x_url_label.setText(f"X投稿内の計測用記事URL: {post.x_url}")
        self._set_post_actions_enabled(True)
        self._loading_post = False
        self._schedule_draft()
        self._sync_subtitle_editor()

    def _schedule_draft(self) -> None:
        if self._loading_post or self._post is None:
            return
        self._draft_completed = False
        self.draft_status_label.setText("下書きを保存しています…")
        self._draft_timer.start()

    def _save_draft(self) -> bool:
        self._draft_timer.stop()
        if self._loading_post or self._post is None or self._draft_completed:
            return True
        try:
            post = self._post
            reading = self.narration_text_edit.toPlainText()
            manually_edited = self._narration_manually_edited
            if self.subtitle_editor.has_pending_edits():
                subtitle, pending_reading = self.subtitle_editor.pending_scripts()
                post = replace(post, tiktok_script=subtitle)
                manually_edited = manually_edited or pending_reading != reading
                reading = pending_reading
            self.controller.draft_repository.save(
                post, reading, manually_edited
            )
        except Exception as exc:
            self.draft_status_label.setText(f"下書きを保存できませんでした。「下書きを保存」で再試行してください。{exc}")
            return False
        self.draft_status_label.setText(f"下書き保存済み {datetime.now():%H:%M:%S} · 「下書きから再開」で続けられます。")
        return True

    def _show_draft_availability(self) -> None:
        try:
            drafts = self.controller.draft_repository.list_drafts()
            if self.controller.draft_repository.warnings:
                self.draft_status_label.setText(self.controller.draft_repository.warnings[0])
            elif drafts:
                self.draft_status_label.setText(f"保存した下書きが{len(drafts)}件あります。「下書きから再開」を押してください。")
        except Exception as exc:
            self.draft_status_label.setText(f"下書き一覧を読み込めませんでした。{exc}")

    def _open_drafts(self) -> None:
        if not self._save_draft():
            return
        try:
            drafts = self.controller.draft_repository.list_drafts()
        except Exception as exc:
            self._show_error("下書きを開けませんでした", exc)
            return
        if self.controller.draft_repository.warnings:
            self.draft_status_label.setText(self.controller.draft_repository.warnings[0])
        if not drafts:
            self.status_label.setText("保存した下書きはありません。投稿セットを作ると自動保存されます。")
            return
        dialog = DraftDialog(drafts, parent=self)
        if dialog.exec() and (draft := dialog.selected_draft()) is not None:
            self._restore_draft(draft)

    def _restore_draft(self, draft: Draft) -> None:
        self._display_post(draft.post)
        self._loading_post = True
        try:
            self._set_narration_text(draft.narration_script, status="保存した音声用の読みを復元しました。")
            self._narration_manually_edited = draft.narration_manually_edited
        finally:
            self._loading_post = False
        self._draft_timer.stop()
        self._sync_subtitle_editor()
        self.draft_status_label.setText(f"{draft.updated_at:%m/%d %H:%M}の下書きを復元しました。")
        self.status_label.setText("下書きの続きから編集できます。音声は現在の設定で再確認してください。")

    def _mark_posted(self) -> None:
        self._apply_pending_card_edits()
        if self._post is None:
            return
        answer = QMessageBox.question(
            self,
            "投稿済みにしますか？",
            "TikTokまたはXへの手動投稿が終わった場合だけ「はい」を押してください。\nこの記事は通常の自動選定から除外されます。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.mark_current_posted()
        except AlreadyPostedError:
            QMessageBox.information(self, "登録済み", "この記事はすでに投稿履歴へ登録されています。")
        except Exception as exc:
            self._show_error("投稿履歴へ保存できませんでした", exc)
            return
        self.posted_button.setEnabled(False)
        self._draft_timer.stop()
        self._draft_completed = True
        try:
            self.controller.draft_repository.complete_article(self._post.article.article_key)
            self.draft_status_label.setText("投稿済みのため、下書き一覧から外しました。")
        except Exception as exc:
            self.draft_status_label.setText(f"投稿履歴は保存済みですが、下書きの完了状態を保存できませんでした。{exc}")
        self.status_label.setText("投稿済みとして保存しました。次回から通常の候補には表示されません。")

    def _open_history(self) -> None:
        try:
            records = self.controller.history()
            dialog = HistoryDialog(
                records,
                update_memo=self.controller.history_repository.update_memo,
                unpost=self.controller.history_repository.unmark_posted,
                parent=self,
            )
            dialog.exec()
        except Exception as exc:
            self._show_error("投稿履歴を開けませんでした", exc)

    def _open_settings(self) -> None:
        if not self._save_draft():
            return
        dialog = SettingsDialog(self.controller.settings, parent=self)
        if not dialog.exec():
            return
        try:
            count = self.controller.save_settings(dialog.settings_value())
        except Exception as exc:
            self._show_error("設定を保存できませんでした", exc)
            return
        self._post = None
        self._clear_post()
        self._update_voice_status()
        self.status_label.setText(f"設定を保存し、{count:,}件の記事を読み込みました。")

    def _record_voice(self) -> None:
        if self._post is None:
            QMessageBox.information(
                self,
                "先にTikTok台本を作ってください",
                "「今日の投稿を作る」を押してTikTok台本を表示してから、"
                "「自分の声を登録」を押してください。",
            )
            return
        recording_script = self.tiktok_text.toPlainText().strip()
        if not recording_script:
            QMessageBox.information(
                self,
                "TikTok台本がありません",
                "先にTikTok台本を作ってから、もう一度お試しください。",
            )
            return
        samples_dir = voice_samples_dir()
        samples_dir.mkdir(parents=True, exist_ok=True)
        configured = Path(self.controller.settings.voice_sample_path)
        existing = configured if configured.is_file() else None
        destination = existing or (
            samples_dir / f"voice-sample-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
        )
        dialog = VoiceRecordingDialog(destination, recording_script, parent=self)
        accepted = bool(dialog.exec())
        sample_path = dialog.accepted_voice_path()
        reference_text = dialog.accepted_reference_text()
        if not accepted or sample_path is None:
            if existing is None:
                destination.unlink(missing_ok=True)
            return
        self.status_label.setText(
            "録音を保存しました。Voiceboxへ自分の声として登録しています…"
        )
        self._start_background_task(
            lambda: self.controller.register_voice_sample(
                sample_path,
                reference_text,
            ),
            success=self._voice_registered,
            error_title="Voiceboxへ自分の声を登録できませんでした",
        )

    def _voice_registered(self, result: object) -> None:
        if not isinstance(result, VoiceProfile):
            self._background_failed(RuntimeError("Voiceboxの登録結果を読み取れませんでした。"))
            return
        self._update_voice_status()
        self.status_label.setText(
            "自分の声を登録しました。これから作る動画では、この声を最初に使用します。"
        )
        QMessageBox.information(
            self,
            "自分の声を登録しました",
            "録音をVoiceboxへ登録しました。\n次に投稿セットを作り、「動画を作る」を押してください。",
        )

    def _generate_video(self) -> None:
        self._apply_pending_card_edits()
        if self._post is None:
            QMessageBox.information(
                self,
                "先に投稿セットを作ってください",
                "「今日の投稿を作る」を押して、動画にする台本を表示してください。",
            )
            return
        if self._voice_preview is None or not self._voice_preview.path.is_file():
            QMessageBox.information(
                self,
                "先にVOICEVOX音声を確認してください",
                "「① VOICEVOX音声を確認」を押して読み上げを確認すると、"
                "動画を作れるようになります。",
            )
            return
        voice_script = self.narration_text_edit.toPlainText()
        if not voice_script.strip():
            QMessageBox.information(
                self,
                "音声用の読みがありません",
                "「音声用の読み」タブを開き、読みを入力するか、"
                "「台本から読みを作り直す」を押してください。",
            )
            return
        self._stop_voice_preview()
        self.status_label.setText(
            "ナレーションと字幕を合わせてTikTok動画を書き出しています。数分かかることがあります…"
        )
        self._start_background_task(
            lambda progress: self.controller.generate_current_video(
                progress,
                narration_script=voice_script,
                voice_preview=self._voice_preview,
            ),
            success=self._video_generated,
            error_title="TikTok動画を作れませんでした",
            with_progress=True,
        )

    def _preview_voice(self) -> None:
        self._apply_pending_card_edits()
        if self._post is None:
            QMessageBox.information(
                self,
                "先に投稿セットを作ってください",
                "「今日の投稿を作る」を押して、音声にする台本を表示してください。",
            )
            return
        if self._preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._preview_player.stop()
            return
        if self._voice_preview is not None and self._voice_preview.path.is_file():
            self._playing_card_preview = False
            self._preview_player.setSource(
                QUrl.fromLocalFile(str(self._voice_preview.path.resolve()))
            )
            self._preview_player.play()
            self.status_label.setText("全体の確認音声を再生しています。読み方を確認してから動画を作成してください。")
            return
        voice_script = self.narration_text_edit.toPlainText()
        if not voice_script.strip():
            QMessageBox.information(
                self,
                "音声用の読みがありません",
                "「音声用の読み」タブを開き、読みを入力するか、"
                "「台本から読みを作り直す」を押してください。",
            )
            return
        self._stop_voice_preview()
        self.status_label.setText(
            "VOICEVOXで確認用の音声を作っています。完成すると自動で再生します…"
        )
        self._start_background_task(
            lambda progress: self.controller.generate_current_voice_preview(
                progress,
                narration_script=voice_script,
            ),
            success=self._voice_preview_generated,
            error_title="VOICEVOXの確認音声を作れませんでした",
            with_progress=True,
        )

    def _voice_preview_generated(self, result: object) -> None:
        if not isinstance(result, GeneratedVoicePreview):
            self._background_failed(RuntimeError("確認音声の情報を読み取れませんでした。"))
            return
        self._voice_preview = result
        self._playing_card_preview = False
        self._preview_player.setSource(QUrl.fromLocalFile(str(result.path.resolve())))
        self._preview_player.play()
        self.status_label.setText(
            "VOICEVOXの確認音声を再生しています。読み方を確認し、問題なければ「② 動画を作る」を押してください。"
        )

    def _preview_voice_card(self, card_index: int) -> None:
        if self._post is None or (self._background_task is not None and self._background_task.isRunning()):
            return
        voice_script = self.narration_text_edit.toPlainText()
        self._stop_voice_preview()
        self.status_label.setText(f"字幕{card_index + 1}枚目の音声を用意しています。未変更の音声は再利用します。")
        self._start_background_task(
            lambda progress: self.controller.generate_current_voice_card_preview(
                card_index, progress, narration_script=voice_script
            ),
            success=self._voice_card_preview_generated,
            error_title="選んだ字幕の音声を作れませんでした",
            with_progress=True,
        )

    def _voice_card_preview_generated(self, result: object) -> None:
        if not isinstance(result, GeneratedVoiceCardPreview):
            self._background_failed(RuntimeError("部分音声の情報を読み取れませんでした。"))
            return
        self._playing_card_preview = True
        self._preview_player.setSource(QUrl.fromLocalFile(str(result.path.resolve())))
        self._preview_player.play()
        self.status_label.setText(
            f"字幕{result.card_index + 1}枚目を試聴中です。動画を作る前に「① VOICEVOX音声を確認」で全体を確認してください。"
        )

    def _voice_preview_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.voice_preview_button.setText("① 音声を止める")
        elif self._playing_card_preview:
            self.voice_preview_button.setText("① 音声をもう一度再生" if self._voice_preview else "① VOICEVOX音声を確認")
        elif self._voice_preview is not None:
            self.voice_preview_button.setText("① 音声をもう一度再生")
            self.status_label.setText(
                "VOICEVOXの確認音声を聞き終わりました。問題なければ「② 動画を作る」を押してください。"
            )
        else:
            self.voice_preview_button.setText("① VOICEVOX音声を確認")

    def _show_voice_preview_playback_error(
        self,
        _error,
        error_string: str,
    ) -> None:  # type: ignore[no-untyped-def]
        if not error_string:
            return
        self.status_label.setText(
            "確認音声を再生できませんでした。Windowsの音声出力を確認してください。"
        )

    def _stop_voice_preview(self) -> None:
        self._preview_player.stop()
        self._preview_player.setSource(QUrl())
        self._playing_card_preview = False
        QCoreApplication.processEvents()

    def _invalidate_voice_preview(self) -> None:
        self._stop_voice_preview()
        self._voice_preview = None
        if hasattr(self, "voice_preview_button"):
            self.voice_preview_button.setText("① VOICEVOX音声を確認")
        if hasattr(self, "video_button"):
            self.video_button.setEnabled(False)

    def _video_generated(self, result: object) -> None:
        if not isinstance(result, GeneratedMedia):
            self._background_failed(RuntimeError("完成動画の情報を読み取れませんでした。"))
            return
        self._last_video_path = result.video.output_path
        self.open_video_button.setEnabled(True)
        voice_label = "自分の声" if result.narration_provider == "voicebox" else "VOICEVOX"
        self.status_label.setText(
            f"TikTok動画を作成しました（ナレーション: {voice_label}）。内容を確認してから手動で投稿してください。"
        )
        message = (
            f"完成動画を保存しました。\n\n{result.video.output_path}\n\n"
            "「完成動画を開く」で字幕とナレーションを確認してください。\n\n"
            "TikTokへ手動投稿するときは「AI生成コンテンツ」と"
            "「自分のブランド・事業を宣伝」の表示をオンにしてください。"
        )
        if result.fallback_reason:
            message += (
                "\n\n今回はVoiceboxを使えなかったため、予備のVOICEVOXへ切り替えました。"
                "自分の声を使うにはVoiceboxを起動してから作り直してください。"
            )
        QMessageBox.information(self, "TikTok動画ができました", message)

    def _open_last_video(self) -> None:
        if self._last_video_path is None or not self._last_video_path.is_file():
            QMessageBox.information(
                self,
                "完成動画がありません",
                "先に投稿セットを作り、「動画を作る」を押してください。",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_video_path)))

    def _open_video_folder(self) -> None:
        folder = generated_videos_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _update_voice_status(self) -> None:
        settings = self.controller.settings
        if settings.voice_engine == "voicevox":
            speaker = (
                "小夜/SAYO"
                if settings.voicevox_speaker_id == 46
                else f"話者番号 {settings.voicevox_speaker_id}"
            )
            text = f"ナレーション: VOICEVOX（{speaker}）"
            self.voice_button.setVisible(False)
        elif settings.voicebox_profile_id:
            text = "自分の声: Voiceboxへ登録済み"
            self.voice_button.setVisible(True)
        elif settings.voice_sample_path and Path(settings.voice_sample_path).is_file():
            text = "自分の声: 録音済み・Voicebox未登録"
            self.voice_button.setVisible(True)
        else:
            text = "自分の声: 未登録（先に録音してください）"
            self.voice_button.setVisible(True)
        self.voice_status_label.setText(text)

    def _start_background_task(
        self,
        function,
        *,
        success,
        error_title: str,
        with_progress: bool = False,
    ) -> None:  # type: ignore[no-untyped-def]
        if self._background_task is not None and self._background_task.isRunning():
            return
        self._background_error_title = error_title
        self._set_media_busy(True)
        task = BackgroundTask(function, parent=self, with_progress=with_progress)
        self._background_task = task
        task.succeeded.connect(success)
        task.failed.connect(self._background_failed)
        if with_progress:
            task.progressed.connect(self._media_progressed)
            self._begin_media_progress()
        task.finished.connect(self._background_finished)
        task.start()

    def _background_failed(self, error: object) -> None:
        exc = error if isinstance(error, Exception) else RuntimeError(str(error))
        self._update_voice_status()
        self.status_label.setText(self._background_error_title)
        if self._background_error_title.startswith("Voicebox"):
            guidance = (
                "録音はPC内に保存されています。Voiceboxを起動して、もう一度お試しください。"
            )
        else:
            guidance = (
                "VoiceboxまたはVOICEVOXを起動して、もう一度お試しください。"
            )
        QMessageBox.critical(
            self,
            self._background_error_title,
            f"{exc}\n\n{guidance}",
        )

    def _background_finished(self) -> None:
        task = self._background_task
        self._background_task = None
        self._set_media_busy(False)
        self._finish_media_progress()
        if task is not None:
            task.deleteLater()

    def _set_media_busy(self, busy: bool) -> None:
        self.subtitle_editor.set_busy(busy)
        self.settings_button.setEnabled(not busy)
        self.drafts_button.setEnabled(not busy)
        self.save_draft_button.setEnabled(not busy and self._post is not None)
        self.tiktok_text.setReadOnly(busy)
        self.narration_text_edit.setReadOnly(busy)
        self.reset_narration_button.setEnabled(not busy and self._post is not None)
        self.voice_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.change_button.setEnabled(not busy and self._post is not None)
        self.voice_preview_button.setEnabled(not busy and self._post is not None)
        self.video_button.setEnabled(
            not busy
            and self._post is not None
            and self._voice_preview is not None
        )
        if busy:
            self.posted_button.setEnabled(False)
        elif self._post is not None:
            self.posted_button.setEnabled(True)

    def _begin_media_progress(self) -> None:
        self._media_elapsed_seconds = 0
        self.media_progress_bar.setRange(0, 100)
        self.media_progress_bar.setValue(0)
        self.media_progress_label.setText("動画作成を開始しています")
        self.media_elapsed_label.setText("経過 00:00")
        self.media_progress_bar.setVisible(True)
        self.media_progress_label.setVisible(True)
        self.media_elapsed_label.setVisible(True)
        self._media_timer.start()

    def _media_progressed(self, percent: int, message: str) -> None:
        if percent < 0:
            self.media_progress_bar.setRange(0, 0)
            self.media_progress_bar.setFormat("")
        else:
            self.media_progress_bar.setRange(0, 100)
            self.media_progress_bar.setValue(max(0, min(100, percent)))
            self.media_progress_bar.setFormat("%p%")
        self.media_progress_label.setText(message)
        self.status_label.setText(message)

    def _update_media_elapsed(self) -> None:
        self._media_elapsed_seconds += 1
        minutes, seconds = divmod(self._media_elapsed_seconds, 60)
        self.media_elapsed_label.setText(f"経過 {minutes:02d}:{seconds:02d}")

    def _finish_media_progress(self) -> None:
        self._media_timer.stop()
        self.media_progress_bar.setVisible(False)
        self.media_progress_label.setVisible(False)
        self.media_elapsed_label.setVisible(False)

    def _copy(self, text: str, label: str) -> None:
        if not text.strip():
            QMessageBox.information(self, "コピーする内容がありません", "先に今日の投稿セットを作ってください。")
            return
        QGuiApplication.clipboard().setText(text)
        self.status_label.setText(f"{label}をクリップボードへコピーしました。")

    def _copy_x_part(self, index: int) -> None:
        first, second = split_x_thread(self.x_text.toPlainText())
        parts = (first, second)
        self._copy(parts[index], f"Xの{index + 1}つ目の投稿")

    def _copy_article_url(self) -> None:
        if self._post is None:
            return
        # 動画用ボタンなので既定はTikTok計測用URL。X本文にはX用URLが含まれる。
        self._copy(self._post.tiktok_url, "TikTok用の記事URL")

    def _show_load_status(self) -> None:
        count = len(self.controller.articles)
        if count:
            suffix = f"（注意 {len(self.controller.load_warnings)}件）" if self.controller.load_warnings else ""
            self.status_label.setText(f"記事を{count:,}件読み込みました。{suffix}")
        else:
            self.status_label.setText("記事が見つかりません。右上の「設定」から記事フォルダを選んでください。")

    def _clear_post(self) -> None:
        self.category_label.setText("—")
        self.type_label.setText("—")
        self.gender_label.setText("—")
        self.article_title.setText("まだ記事は選ばれていません")
        self.catchphrase_label.setText("「今日の投稿を作る」を押してください。")
        self.tiktok_text.clear()
        self._set_narration_text(
            "",
            status="投稿セットを作ると、自動補正した読みが表示されます。",
        )
        self.x_text.clear()
        self.chatgpt_text.clear()
        self.tiktok_stats.setText("読み上げ時間: —")
        self.x_stats.setText("X文字数: —")
        self.hashtags_label.setText("ハッシュタグ: —")
        self.tiktok_url_label.setText("TikTok用記事URL: —")
        self.x_url_label.setText("X投稿内の計測用記事URL: —")
        self._set_post_actions_enabled(False)

    def _set_post_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.change_button,
            self.save_draft_button,
            self.posted_button,
            self.voice_preview_button,
            self.reset_narration_button,
            self.copy_x_first_button,
            self.copy_x_second_button,
            self.copy_script_button,
            self.copy_url_button,
            self.copy_prompt_button,
        ):
            button.setEnabled(enabled)
        self.video_button.setEnabled(enabled and self._voice_preview is not None)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._background_task is not None and self._background_task.isRunning():
            QMessageBox.information(
                self,
                "処理が終わるまでお待ちください",
                "音声または動画を作成中です。完了してから画面を閉じてください。",
            )
            event.ignore()
            return
        self._stop_voice_preview()
        if not self._save_draft():
            event.ignore()
            return
        super().closeEvent(event)

    def _show_error(self, title: str, exc: Exception) -> None:
        self.status_label.setText(title)
        QMessageBox.critical(
            self,
            title,
            f"{exc}\n\n記事フォルダの場所や設定を確認してください。解決しない場合は、このメッセージを控えてください。",
        )
