from dataclasses import replace
import os
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor

from stellalog_sns.media_service import GeneratedVoiceCardPreview, GeneratedVoicePreview
from stellalog_sns.ui.main_window import MainWindow
from test_drafts import _controller, _post


def _window(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(_controller(tmp_path))
    window._display_post(replace(_post(), tiktok_script="口を開く\n\n話す"))
    return app, window


def test_card_edit_updates_full_script_and_auto_reading_without_moving_cursor(tmp_path):
    app, window = _window(tmp_path)
    window.subtitle_editor.select_card(0)
    editor = window.subtitle_editor.subtitle_edit
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("よ")
    editor.insertPlainText("ね")
    assert editor.toPlainText() == "口を開くよね"
    assert editor.textCursor().position() == len("口を開くよね")
    assert window.tiktok_text.toPlainText() == "口を開くよね\n\n話す"
    assert window.narration_text_edit.toPlainText() == "くちを開くよね\n\n話す"
    window.subtitle_editor.narration_edit.setPlainText("クチをひらくよね")
    assert window._narration_manually_edited
    assert window.narration_text_edit.toPlainText() == "クチをひらくよね\n\n話す"
    window.close()
    app.processEvents()


def test_invalid_card_input_is_saved_and_transferred_when_leaving_editor(tmp_path):
    app, window = _window(tmp_path)
    window.tabs.setCurrentWidget(window.subtitle_editor)
    window.subtitle_editor.subtitle_edit.setPlainText("口を開く\n\nまだ編集中")
    assert window.subtitle_editor.has_pending_edits()
    assert window._save_draft()
    draft = window.controller.draft_repository.list_drafts()[0]
    assert draft.post.tiktok_script == "口を開く\n\nまだ編集中\n\n話す"
    assert window.subtitle_editor.subtitle_edit.toPlainText() == "口を開く\n\nまだ編集中"
    window.tabs.setCurrentIndex(0)
    assert window.tiktok_text.toPlainText() == draft.post.tiktok_script
    window.close()
    app.processEvents()


def test_card_preview_does_not_unlock_video_and_edit_invalidates_full_preview(tmp_path, monkeypatch):
    app, window = _window(tmp_path)
    output = tmp_path / "card.wav"
    with wave.open(str(output), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b"\x00" * 1600)
    monkeypatch.setattr(window._preview_player, "play", lambda: None)
    window._voice_card_preview_generated(GeneratedVoiceCardPreview(output, 0.1, 0))
    window._set_media_busy(False)
    assert window._voice_preview is None
    assert not window.video_button.isEnabled()
    window._voice_preview = GeneratedVoicePreview(output, (0.1, 0.1))
    window._set_media_busy(False)
    assert window.video_button.isEnabled()
    window._preview_voice()
    assert not window._playing_card_preview
    assert "全体" in window.status_label.text()
    window.subtitle_editor.narration_edit.setPlainText("クチをひらく")
    assert window._voice_preview is None
    assert not window.video_button.isEnabled()
    window._set_media_busy(True)
    assert window.tiktok_text.isReadOnly()
    assert window.narration_text_edit.isReadOnly()
    assert not window.drafts_button.isEnabled()
    assert not window.settings_button.isEnabled()
    window._set_media_busy(False)
    window.close()
    app.processEvents()
