from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("設定")
        self.setMinimumWidth(620)

        self.data_dir_edit = QLineEdit(str(settings.data_dir))
        browse_button = QPushButton("フォルダを選ぶ")
        browse_button.clicked.connect(self._browse_data_dir)
        data_row = QHBoxLayout()
        data_row.addWidget(self.data_dir_edit, 1)
        data_row.addWidget(browse_button)

        self.site_origin_edit = QLineEdit(settings.site_origin)
        self.reading_speed_spin = QSpinBox()
        self.reading_speed_spin.setRange(180, 600)
        self.reading_speed_spin.setSuffix(" 文字/分")
        self.reading_speed_spin.setValue(settings.reading_chars_per_minute)

        self.voicevox_speed_spin = QDoubleSpinBox()
        self.voicevox_speed_spin.setRange(0.5, 2.0)
        self.voicevox_speed_spin.setDecimals(2)
        self.voicevox_speed_spin.setSingleStep(0.05)
        self.voicevox_speed_spin.setSuffix(" 倍")
        self.voicevox_speed_spin.setValue(settings.voicevox_speed_scale)
        self.voicevox_speed_spin.setToolTip(
            "1.00倍が標準です。小夜/SAYOを少し速くする場合は1.15〜1.25倍が目安です。"
        )

        self.quota_spins: dict[str, QSpinBox] = {}
        quota_labels = {
            "personality": "性格",
            "ranking": "ランキング",
            "love": "恋愛",
            "work_money": "仕事・金運",
            "reunion_night": "復縁・夜",
        }
        quota_widget = QWidget()
        quota_layout = QHBoxLayout(quota_widget)
        quota_layout.setContentsMargins(0, 0, 0, 0)
        for key, label in quota_labels.items():
            spin = QSpinBox()
            spin.setRange(0, 7)
            spin.setValue(settings.weekly_quotas.get(key, 0))
            spin.setToolTip(label)
            self.quota_spins[key] = spin
            quota_layout.addWidget(QLabel(label))
            quota_layout.addWidget(spin)

        form = QFormLayout()
        form.addRow("記事データ:", data_row)
        form.addRow("公開サイトURL:", self.site_origin_edit)
        form.addRow("台本の時間見積もり:", self.reading_speed_spin)
        form.addRow("VOICEVOXの音声速度:", self.voicevox_speed_spin)
        form.addRow("1週間の配分:", quota_widget)

        help_label = QLabel(
            "選ぶフォルダには article-index.json と articles フォルダが必要です。\n"
            "VOICEVOXは1.00倍が標準です。StellaLog側へ書き込むことはありません。"
            "週間配分の合計は7にしてください。"
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("helpText")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(help_label)
        layout.addWidget(buttons)

    def _browse_data_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "記事のデータフォルダを選ぶ",
            self.data_dir_edit.text(),
        )
        if selected:
            self.data_dir_edit.setText(selected)

    def _validate_and_accept(self) -> None:
        data_dir = Path(self.data_dir_edit.text().strip())
        if not (data_dir / "article-index.json").is_file() or not (
            data_dir / "articles"
        ).is_dir():
            QMessageBox.warning(
                self,
                "記事フォルダを確認してください",
                "選んだ場所に article-index.json と articles フォルダが見つかりません。",
            )
            return

        site_origin = self.site_origin_edit.text().strip().rstrip("/")
        if not site_origin.startswith(("https://", "http://")):
            QMessageBox.warning(
                self,
                "公開サイトURLを確認してください",
                "公開サイトURLは https:// または http:// から入力してください。",
            )
            return

        if sum(spin.value() for spin in self.quota_spins.values()) != 7:
            QMessageBox.warning(
                self,
                "週間配分を確認してください",
                "週間配分の合計を7にしてください。",
            )
            return
        self.accept()

    def settings_value(self) -> AppSettings:
        return replace(
            self._settings,
            data_dir=Path(self.data_dir_edit.text().strip()),
            site_origin=self.site_origin_edit.text().strip().rstrip("/"),
            reading_chars_per_minute=self.reading_speed_spin.value(),
            voicevox_speed_scale=self.voicevox_speed_spin.value(),
            weekly_quotas={key: spin.value() for key, spin in self.quota_spins.items()},
        )
