from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stellalog_sns.controller import StudioController
from stellalog_sns.history_repository import HistoryRepository
from stellalog_sns.media_service import GeneratedVoicePreview
from stellalog_sns.models import AppSettings, HistoryRecord
from stellalog_sns.settings import SettingsStore
from stellalog_sns.ui.history_dialog import HistoryDialog
from stellalog_sns.ui.main_window import MainWindow
from stellalog_sns.ui.settings_dialog import SettingsDialog


def _write_article_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    article_path = data_dir / "articles" / "love" / "female" / "enfj" / "aquarius.json"
    article_path.parent.mkdir(parents=True)
    (data_dir / "article-index.json").write_text(
        json.dumps(["love/female/enfj/aquarius"]), encoding="utf-8"
    )
    article_path.write_text(
        json.dumps(
            {
                "mbti": "enfj",
                "zodiac": "aquarius",
                "gender": "female",
                "concern": "love",
                "title": "ENFJ×水瓶座の女性の恋愛傾向",
                "sns_catchphrase": "理想を大切にする恋愛タイプ",
                "content": [
                    {"type": "h3", "text": "気持ちを丁寧に確かめる"},
                    {
                        "type": "p",
                        "text": "相手との考え方の共通点を大切にする傾向があります。"
                        "一方で、考えすぎて動き出すまで時間がかかることがあります。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return data_dir


def _controller(tmp_path: Path) -> StudioController:
    data_dir = _write_article_data(tmp_path)
    settings_store = SettingsStore(tmp_path / "app")
    settings_store.save(AppSettings(data_dir=data_dir))
    return StudioController(
        settings_store=settings_store,
        history_repository=HistoryRepository(tmp_path / "app"),
    )


def test_main_window_uses_internal_filter_values_and_japanese_labels(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(_controller(tmp_path))

    window.category_combo.setCurrentIndex(window.category_combo.findData("love"))
    window.mbti_combo.setCurrentIndex(window.mbti_combo.findData("enfj"))
    window.zodiac_combo.setCurrentIndex(window.zodiac_combo.findData("aquarius"))
    window.gender_combo.setCurrentIndex(window.gender_combo.findData("female"))

    filters = window._filters()
    assert filters.concern == "love"
    assert filters.mbti == "enfj"
    assert filters.zodiac == "aquarius"
    assert filters.gender == "female"

    post_set = window.controller.create_post(filters)
    window._display_post(post_set)

    assert window.category_label.text() == "恋愛"
    assert window.type_label.text() == "ENFJ水瓶座"
    assert window.gender_label.text() == "女性"
    assert window.tiktok_stats.text().startswith("読み上げ時間: 約")
    assert "." not in window.tiktok_stats.text()
    assert window.copy_x_first_button.isEnabled()
    assert window.copy_x_second_button.isEnabled()
    assert window.voice_preview_button.isEnabled()
    assert not window.video_button.isEnabled()
    assert window.voice_button.isEnabled()
    assert "自分の声" in window.voice_status_label.text()
    assert "1つ目" in window.x_stats.text()
    assert "2つ目" in window.x_stats.text()
    assert "日本語約" in window.x_stats.text()
    assert window.media_progress_bar.isHidden()
    assert not window.tiktok_text.isReadOnly()
    assert "通常の改行は同じ字幕内" in window.tiktok_edit_help.text()
    assert "空白行で次の字幕" in window.tiktok_edit_help.text()
    assert "音声だけ自動補正" in window.tiktok_edit_help.text()
    assert window.tabs.tabText(1) == "音声用の読み"
    assert window.narration_text_edit.toPlainText()
    assert window.reset_narration_button.isEnabled()

    preview_path = tmp_path / "voicevox-preview.wav"
    preview_path.write_bytes(b"RIFF....WAVE")
    window._voice_preview = GeneratedVoicePreview(preview_path, (1.0,))
    window._set_post_actions_enabled(True)
    assert window.video_button.isEnabled()

    edited_script = "1枚目の1行目\n1枚目の2行目\n\n2枚目の字幕"
    window.tiktok_text.setPlainText(edited_script)
    assert window._voice_preview is None
    assert not window.video_button.isEnabled()
    assert window.controller.current_post is not None
    assert window.controller.current_post.tiktok_script == edited_script
    assert window._post is not None
    assert window._post.tiktok_script == edited_script
    assert window.narration_text_edit.toPlainText() == edited_script

    window.tiktok_text.setPlainText("口を開く")
    assert window.narration_text_edit.toPlainText() == "くちを開く"
    window.narration_text_edit.setPlainText("クチを開く")
    window.tiktok_text.setPlainText("口を開いて話す")
    assert window.narration_text_edit.toPlainText() == "クチを開く"
    assert "確認してください" in window.narration_status_label.text()
    window.reset_narration_button.click()
    assert window.narration_text_edit.toPlainText() == "くちを開いて話す"

    window._begin_media_progress()
    window._media_progressed(-1, "Voiceboxでナレーションを作成中です")
    assert not window.media_progress_bar.isHidden()
    assert window.media_progress_bar.minimum() == 0
    assert window.media_progress_bar.maximum() == 0
    assert "Voicebox" in window.media_progress_label.text()
    window._update_media_elapsed()
    assert window.media_elapsed_label.text() == "経過 00:01"

    window._media_progressed(75, "NVIDIA GPUで動画を書き出しています")
    assert window.media_progress_bar.maximum() == 100
    assert window.media_progress_bar.value() == 75
    window._finish_media_progress()
    assert window.media_progress_bar.isHidden()
    window.close()
    app.processEvents()


def test_history_dialog_can_update_slots_record_memo() -> None:
    app = QApplication.instance() or QApplication([])
    record = HistoryRecord(
        id=1,
        article_key="love/female/enfj/aquarius",
        selected_at=datetime(2026, 9, 1, 9, 0),
        posted_at=datetime(2026, 9, 1, 10, 0),
        category="love",
        mbti="enfj",
        zodiac="aquarius",
        gender="female",
        article_title="ENFJ×水瓶座の女性の恋愛傾向",
        source_path="sample.json",
        public_url="https://n-stellalog.com/reading/enfj/aquarius/female/love",
        tiktok_url="https://example.test/?utm_source=tiktok",
        x_url="https://example.test/?utm_source=x",
        tiktok_script="台本",
        x_post="投稿文",
        hashtags=("#MBTI",),
        tiktok_template_id="tiktok_question_opening",
        x_template_id="x_relatable",
        is_posted=True,
    )
    updates: list[tuple[int, str]] = []
    dialog = HistoryDialog(
        [record],
        update_memo=lambda record_id, memo: updates.append((record_id, memo)),
        unpost=lambda _record_id: None,
    )
    dialog.memo_edit.setText("反応が良かった")
    dialog._save_memo()

    assert updates == [(1, "反応が良かった")]
    assert dialog._records[0].memo == "反応が良かった"
    dialog.close()
    app.processEvents()


def test_settings_dialog_can_select_voicevox_speed() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(AppSettings(voicevox_speed_scale=1.2))

    assert dialog.voicevox_speed_spin.minimum() == 0.5
    assert dialog.voicevox_speed_spin.maximum() == 2.0
    assert dialog.voicevox_speed_spin.value() == 1.2

    dialog.voicevox_speed_spin.setValue(1.35)

    assert dialog.settings_value().voicevox_speed_scale == 1.35
    dialog.close()
    app.processEvents()


def test_voicevox_mode_shows_sayo_and_hides_voicebox_recording(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    controller = _controller(tmp_path)
    controller.settings = AppSettings(
        data_dir=controller.settings.data_dir,
        voice_engine="voicevox",
        voicevox_speaker_id=46,
        voicevox_speed_scale=1.2,
    )
    window = MainWindow(controller)

    assert "VOICEVOX（小夜/SAYO）" in window.voice_status_label.text()
    assert window.voice_button.isHidden()

    post_set = window.controller.create_post(window._filters())
    window._display_post(post_set)
    window.tiktok_text.setPlainText("一枚目\n二行目\n\n次の字幕")
    assert window._post is not None
    expected = len(window._post.tiktok_script) / (330 * 1.2) * 60
    assert window._post.estimated_tiktok_seconds == expected

    window.close()
    app.processEvents()
