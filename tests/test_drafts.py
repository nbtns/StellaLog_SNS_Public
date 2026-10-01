from dataclasses import replace
from datetime import datetime
import os
import json
from pathlib import Path
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stellalog_sns.controller import StudioController
from stellalog_sns.draft_repository import DraftRepository
from stellalog_sns.history_repository import HistoryRepository
from stellalog_sns.models import AppSettings, Article, ContentBlock, PostSet
from stellalog_sns.settings import SettingsStore
from stellalog_sns.ui.main_window import MainWindow


def _post() -> PostSet:
    article = Article("love/female/enfj/aquarius", "love", "female", "enfj", "aquarius",
                      "ENFJ×水瓶座の恋愛", (ContentBlock("p", "相手の気持ちを大切にする。"),),
                      "気持ちを大切にする", Path("missing-source.json"))
    return PostSet(article, datetime(2026, 9, 5, 10, 0), "口を開く\nゆっくりと\n\n話す", "1投稿目\n\n2投稿目",
                   "https://example.com", "https://example.com?tiktok", "https://example.com?x",
                   ("#StellaLog",), "tiktok_a", "x_a", ("相手の気持ちを大切にする。",), 10.0, 20)


def _controller(tmp_path: Path) -> StudioController:
    store = SettingsStore(tmp_path)
    store.save(AppSettings(data_dir=tmp_path / "missing-data"))
    return StudioController(store, HistoryRepository(tmp_path))


def test_draft_roundtrip_updates_same_draft_preserves_blank_lines_and_source(tmp_path):
    repository = DraftRepository(tmp_path)
    post = _post()
    key = repository.save(post, "くちをひらく\nゆっくりと\n\nはなす", True)
    assert repository.save(replace(post, tiktok_script="編集中\n\n"), "\n編集中のよみ\n\n", True) == key
    saved = DraftRepository(tmp_path).list_drafts()
    assert len(saved) == 1
    assert saved[0].post.tiktok_script == "編集中\n\n"
    assert saved[0].narration_script == "\n編集中のよみ\n\n"
    assert saved[0].post.article == post.article
    assert saved[0].post.hashtags == post.hashtags
    assert saved[0].narration_manually_edited


def test_drafts_keep_multiple_sessions_and_complete_without_deleting(tmp_path):
    repository = DraftRepository(tmp_path)
    repository.save(_post(), "読み", False)
    repository.save(replace(_post(), selected_at=datetime(2026, 9, 5, 11, 0)), "別の下書き", True)
    assert len(repository.list_drafts()) == 2
    repository.complete_article(_post().article.article_key)
    assert repository.list_drafts() == []
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 2


def test_corrupt_draft_is_retained_and_other_draft_remains_readable(tmp_path):
    repository = DraftRepository(tmp_path)
    key = repository.save(_post(), "読み", False)
    repository.save(replace(_post(), selected_at=datetime(2026, 9, 5, 11, 0)), "残る読み", False)
    with sqlite3.connect(repository.path) as connection:
        connection.execute("UPDATE drafts SET payload=? WHERE id=?", ("{broken", key))
    assert len(repository.list_drafts()) == 1
    assert repository.warnings
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT payload FROM drafts WHERE id=?", (key,)).fetchone()[0] == "{broken"


def test_parseable_draft_with_wrong_field_type_is_not_offered_for_restore(tmp_path):
    repository = DraftRepository(tmp_path)
    key = repository.save(_post(), "読み", False)
    with sqlite3.connect(repository.path) as connection:
        payload = json.loads(connection.execute("SELECT payload FROM drafts WHERE id=?", (key,)).fetchone()[0])
        payload["post"]["article"]["mbti"] = None
        connection.execute("UPDATE drafts SET payload=? WHERE id=?", (json.dumps(payload), key))
    assert repository.list_drafts() == []
    assert repository.warnings


def test_window_closing_and_reopening_restores_edits_but_requires_audio_confirmation(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = _controller(tmp_path)
    window = MainWindow(controller)
    window._display_post(_post())
    window.tiktok_text.setPlainText("口を開いて\n話す\n\n相手を思う")
    window.narration_text_edit.setPlainText("クチをひらいて\nはなす\n\nあいてをおもう")
    assert window._draft_timer.isActive()
    window.close()
    app.processEvents()
    reopened = MainWindow(_controller(tmp_path))
    drafts = reopened.controller.draft_repository.list_drafts()
    assert len(drafts) == 1
    reopened._restore_draft(drafts[0])
    assert reopened.tiktok_text.toPlainText() == "口を開いて\n話す\n\n相手を思う"
    assert reopened.narration_text_edit.toPlainText() == "クチをひらいて\nはなす\n\nあいてをおもう"
    assert reopened._narration_manually_edited
    assert not reopened.video_button.isEnabled()
    assert reopened.controller.history() == []
    reopened.close()


def test_failed_save_prevents_switching_or_closing_without_losing_edit(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(_controller(tmp_path))
    window._display_post(_post())
    def fail(*args):
        raise OSError("保存先に書き込めません")
    monkeypatch.setattr(window.controller.draft_repository, "save", fail)
    window._create_post()
    assert window._post == _post()
    assert "保存できません" in window.draft_status_label.text()
    assert not window.close()
    monkeypatch.undo()
    window.close()
    app.processEvents()
