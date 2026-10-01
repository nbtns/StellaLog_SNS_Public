from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..labels import (
    CATEGORY_LABELS,
    category_label,
    format_mbti_zodiac,
    gender_label,
    remove_mbti_zodiac_crosses,
    zodiac_label,
)
from ..models import HistoryRecord
from ..x_thread import split_x_thread


class HistoryDialog(QDialog):
    def __init__(
        self,
        records: Sequence[HistoryRecord],
        update_memo: Callable[[int, str], None],
        unpost: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("投稿履歴")
        self.resize(1100, 720)
        self._records = list(records)
        self._filtered: list[HistoryRecord] = []
        self._update_memo = update_memo
        self._unpost = unpost

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("タイトル、MBTI、星座、メモで検索")
        self.category_combo = QComboBox()
        self.category_combo.addItem("全カテゴリー", None)
        for value, label in CATEGORY_LABELS.items():
            self.category_combo.addItem(label, value)
        self.gender_combo = QComboBox()
        self.gender_combo.addItem("すべての性別", None)
        self.gender_combo.addItem("共通", "unisex")
        self.gender_combo.addItem("女性", "female")
        self.gender_combo.addItem("男性", "male")

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.search_edit, 1)
        filter_row.addWidget(self.category_combo)
        filter_row.addWidget(self.gender_combo)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["投稿日", "カテゴリー", "MBTI・星座", "性別", "記事タイトル", "メモ"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.tiktok_text = QPlainTextEdit()
        self.x_text = QPlainTextEdit()
        self.url_text = QPlainTextEdit()
        for edit in (self.tiktok_text, self.x_text, self.url_text):
            edit.setReadOnly(True)
        tabs = QTabWidget()
        tabs.addTab(self.tiktok_text, "TikTok台本")
        tabs.addTab(self.x_text, "X投稿文")
        tabs.addTab(self.url_text, "記事URL")

        copy_tiktok = QPushButton("動画台本をコピー")
        copy_x_first = QPushButton("X 1つ目をコピー")
        copy_x_second = QPushButton("X 2つ目をコピー")
        copy_url = QPushButton("X用URLをコピー")
        copy_tiktok.clicked.connect(lambda: self._copy(self.tiktok_text.toPlainText()))
        copy_x_first.clicked.connect(lambda: self._copy_x_part(0))
        copy_x_second.clicked.connect(lambda: self._copy_x_part(1))
        copy_url.clicked.connect(self._copy_selected_x_url)
        copy_row = QHBoxLayout()
        copy_row.addWidget(copy_tiktok)
        copy_row.addWidget(copy_x_first)
        copy_row.addWidget(copy_x_second)
        copy_row.addWidget(copy_url)
        copy_row.addStretch()

        self.memo_edit = QLineEdit()
        save_memo = QPushButton("メモを保存")
        save_memo.clicked.connect(self._save_memo)
        unpost_button = QPushButton("投稿済みを取り消す")
        unpost_button.clicked.connect(self._mark_unposted)
        memo_row = QHBoxLayout()
        memo_row.addWidget(QLabel("メモ:"))
        memo_row.addWidget(self.memo_edit, 1)
        memo_row.addWidget(save_memo)
        memo_row.addWidget(unpost_button)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(tabs)
        detail_layout.addLayout(copy_row)
        detail_layout.addLayout(memo_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(detail)
        splitter.setSizes([350, 300])

        layout = QVBoxLayout(self)
        layout.addLayout(filter_row)
        layout.addWidget(splitter)

        self.search_edit.textChanged.connect(self._apply_filters)
        self.category_combo.currentIndexChanged.connect(self._apply_filters)
        self.gender_combo.currentIndexChanged.connect(self._apply_filters)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.search_edit.text().strip().casefold()
        category = self.category_combo.currentData()
        gender = self.gender_combo.currentData()
        self._filtered = []
        for record in self._records:
            haystack = " ".join(
                [
                    record.article_title,
                    record.mbti,
                    record.zodiac,
                    zodiac_label(record.zodiac),
                    record.memo,
                ]
            ).casefold()
            if query and query not in haystack:
                continue
            if category and record.category != category:
                continue
            if gender and record.gender != gender:
                continue
            self._filtered.append(record)

        self.table.setRowCount(len(self._filtered))
        for row, record in enumerate(self._filtered):
            values = [
                record.posted_at.strftime("%Y-%m-%d %H:%M"),
                category_label(record.category),
                format_mbti_zodiac(record.mbti, record.zodiac),
                gender_label(record.gender),
                record.article_title,
                record.memo,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.table.setItem(row, column, item)
        if self._filtered:
            self.table.selectRow(0)
        else:
            self._clear_detail()

    def _selected_record(self) -> HistoryRecord | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def _show_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            self._clear_detail()
            return
        self.tiktok_text.setPlainText(remove_mbti_zodiac_crosses(record.tiktok_script))
        self.x_text.setPlainText(remove_mbti_zodiac_crosses(record.x_post))
        self.url_text.setPlainText(
            f"基本URL:\n{record.public_url}\n\nTikTok用:\n{record.tiktok_url}\n\nX用:\n{record.x_url}"
        )
        self.memo_edit.setText(record.memo)

    def _clear_detail(self) -> None:
        self.tiktok_text.clear()
        self.x_text.clear()
        self.url_text.clear()
        self.memo_edit.clear()

    def _save_memo(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        self._update_memo(record.id, self.memo_edit.text().strip())
        index = self._records.index(record)
        self._records[index] = replace(record, memo=self.memo_edit.text().strip())
        self._apply_filters()

    def _mark_unposted(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        answer = QMessageBox.question(
            self,
            "投稿済みを取り消しますか？",
            "履歴は残したまま、未投稿記事の候補へ戻します。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._unpost(record.id)
        self._records = [item for item in self._records if item.id != record.id]
        self._apply_filters()

    def _copy_selected_x_url(self) -> None:
        record = self._selected_record()
        if record is not None:
            self._copy(record.x_url)

    def _copy_x_part(self, index: int) -> None:
        first, second = split_x_thread(self.x_text.toPlainText())
        self._copy((first, second)[index])

    def _copy(self, text: str) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "コピーしました", "クリップボードへコピーしました。")
