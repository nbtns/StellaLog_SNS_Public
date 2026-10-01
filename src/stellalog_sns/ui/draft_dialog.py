from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QPlainTextEdit, QVBoxLayout

from ..draft_repository import Draft


class DraftDialog(QDialog):
    def __init__(self, drafts: list[Draft], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下書きから再開")
        self.resize(720, 580)
        self.drafts = drafts
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("再開する下書きを選んでください。投稿済みにはなりません。"))
        self.list_widget = QListWidget()
        for draft in drafts:
            self.list_widget.addItem(f"{draft.updated_at:%m/%d %H:%M}　{draft.post.article.title}")
        layout.addWidget(self.list_widget)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        self.open_button = buttons.button(QDialogButtonBox.StandardButton.Open)
        self.open_button.setText("この下書きを再開")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("閉じる")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.list_widget.currentRowChanged.connect(self._selected)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept())
        self.open_button.setEnabled(bool(drafts))
        if drafts:
            self.list_widget.setCurrentRow(0)

    def _selected(self, index: int) -> None:
        self.open_button.setEnabled(0 <= index < len(self.drafts))
        self.preview.setPlainText(self.drafts[index].post.tiktok_script if 0 <= index < len(self.drafts) else "")

    def selected_draft(self) -> Draft | None:
        index = self.list_widget.currentRow()
        return self.drafts[index] if 0 <= index < len(self.drafts) else None
