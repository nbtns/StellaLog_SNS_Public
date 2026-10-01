from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from stellalog_sns.ui.subtitle_editor import SubtitleEditor


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _editor() -> SubtitleEditor:
    _app()
    return SubtitleEditor(auto_load_preview=False)


def test_set_scripts_selects_cards_without_emitting_change() -> None:
    editor = _editor()
    changes: list[tuple[str, str]] = []
    editor.scriptsChanged.connect(lambda subtitle, narration: changes.append((subtitle, narration)))

    editor.set_scripts(
        "1枚目の字幕\n同じ画面の2行目\n\n2枚目の字幕",
        "いちまいめの字幕\n同じ画面の二行目\n\nにまいめの字幕",
    )

    assert editor.is_valid()
    assert editor.card_count() == 2
    assert editor.current_card_index() == 0
    assert editor.subtitle_edit.toPlainText() == "1枚目の字幕\n同じ画面の2行目"
    assert editor.narration_edit.toPlainText() == "いちまいめの字幕\n同じ画面の二行目"
    assert changes == []

    editor.select_card(1)
    assert editor.current_card_index() == 1
    assert editor.subtitle_edit.toPlainText() == "2枚目の字幕"
    assert editor.narration_edit.toPlainText() == "にまいめの字幕"
    assert changes == []
    editor.close()


def test_card_edits_update_full_scripts_in_both_directions_once() -> None:
    editor = _editor()
    editor.set_scripts("字幕A\n\n字幕B", "読みA\n\n読みB")
    changes: list[tuple[str, str]] = []
    editor.scriptsChanged.connect(lambda subtitle, narration: changes.append((subtitle, narration)))

    editor.select_card(1)
    editor.subtitle_edit.setPlainText("字幕Bを修正\n同じカード")
    assert changes == [("字幕A\n\n字幕Bを修正\n同じカード", "読みA\n\n読みB")]

    editor.narration_edit.setPlainText("よみビーを修正")
    assert changes == [
        ("字幕A\n\n字幕Bを修正\n同じカード", "読みA\n\n読みB"),
        ("字幕A\n\n字幕Bを修正\n同じカード", "読みA\n\nよみビーを修正"),
    ]
    assert editor.scripts() == changes[-1]
    editor.close()


def test_same_scripts_and_narration_only_refresh_preserve_subtitle_cursor() -> None:
    editor = _editor()
    subtitle = "字幕A\n\n字幕B"
    editor.set_scripts(subtitle, "読みA\n\n読みB")
    editor.select_card(1)
    cursor = editor.subtitle_edit.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.subtitle_edit.setTextCursor(cursor)
    position = editor.subtitle_edit.textCursor().position()
    subtitle_events: list[str] = []
    editor.subtitle_edit.textChanged.connect(
        lambda: subtitle_events.append(editor.subtitle_edit.toPlainText())
    )

    editor.set_scripts(subtitle, "読みA\n\n読みB")
    assert editor.subtitle_edit.textCursor().position() == position
    assert subtitle_events == []

    editor.set_scripts(subtitle, "読みA\n\n新しい読みB")
    assert editor.subtitle_edit.toPlainText() == "字幕B"
    assert editor.subtitle_edit.textCursor().position() == position
    assert editor.narration_edit.toPlainText() == "新しい読みB"
    assert subtitle_events == []
    editor.close()


def test_mismatched_card_counts_are_reported_without_silent_repair() -> None:
    editor = _editor()
    changes: list[tuple[str, str]] = []
    editor.scriptsChanged.connect(lambda subtitle, narration: changes.append((subtitle, narration)))
    subtitle = "字幕A\n\n字幕B"
    narration = "読みA"

    editor.set_scripts(subtitle, narration)

    assert not editor.is_valid()
    assert editor.card_count() == 0
    assert editor.scripts() == (subtitle, narration)
    assert "字幕は2枚" in editor.validation_message()
    assert "音声用の読みは1枚" in editor.validation_message()
    assert not editor.preview_audio_button.isEnabled()
    assert changes == []
    editor.close()


def test_invalid_blank_line_inside_card_does_not_change_scripts_or_emit() -> None:
    editor = _editor()
    editor.set_scripts("字幕A\n\n字幕B", "読みA\n\n読みB")
    original = editor.scripts()
    changes: list[tuple[str, str]] = []
    editor.scriptsChanged.connect(lambda subtitle, narration: changes.append((subtitle, narration)))

    editor.subtitle_edit.setPlainText("字幕A\n\n新しいカード")

    assert not editor.is_valid()
    assert editor.scripts() == original
    assert editor.has_pending_edits()
    assert editor.pending_scripts() == (
        "字幕A\n\n新しいカード\n\n字幕B",
        "読みA\n\n読みB",
    )
    assert "カード内に空白行" in editor.validation_message()
    assert not editor.card_list.isEnabled()
    assert changes == []
    editor.close()


def test_preview_uses_renderer_wrapping_and_rejects_automatic_extra_cards() -> None:
    editor = _editor()
    long_reading = "ながいよみ" * 30
    editor.set_scripts("12345678901234", long_reading)

    assert editor.is_valid()
    assert editor.preview._lines == ("1234567890123", "4")
    assert editor.narration_edit.toPlainText() == long_reading
    assert editor.preview.minimumHeight() == 240

    seven_lines = "\n".join(f"{index}行目" for index in range(1, 8))
    editor.set_scripts(seven_lines, seven_lines)
    assert not editor.is_valid()
    assert "完成動画では2枚" in editor.validation_message()
    assert not editor.preview_audio_button.isEnabled()
    editor.close()


def test_preview_signal_and_busy_state_have_no_extra_emissions() -> None:
    editor = _editor()
    editor.set_scripts("字幕A\n\n字幕B", "読みA\n\n読みB")
    requests: list[int] = []
    changes: list[tuple[str, str]] = []
    editor.previewRequested.connect(requests.append)
    editor.scriptsChanged.connect(lambda subtitle, narration: changes.append((subtitle, narration)))

    editor.select_card(1)
    assert requests == []
    assert changes == []
    editor.preview_audio_button.click()
    assert requests == [1]

    editor.set_busy(True)
    assert not editor.preview_audio_button.isEnabled()
    assert not editor.subtitle_edit.isEnabled()
    editor.preview_audio_button.click()
    assert requests == [1]

    editor.set_busy(False)
    assert editor.preview_audio_button.isEnabled()
    assert editor.subtitle_edit.isEnabled()
    assert changes == []
    editor.close()
