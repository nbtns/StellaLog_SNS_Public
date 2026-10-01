"""デスクトップアプリの起動処理。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont, QFontDatabase

from .controller import StudioController
from .ui.main_window import MainWindow
from .video_renderer import SUBTITLE_FONT_PATH


def configure_ui_font(app: QApplication) -> None:
    """日本語のシステムフォントがない検証環境では同梱フォントを使う。"""
    QFontDatabase.addApplicationFont(str(SUBTITLE_FONT_PATH))
    family = "Yu Gothic UI" if "Yu Gothic UI" in QFontDatabase.families() else "Zen Antique"
    app.setFont(QFont(family, 10))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    configure_ui_font(app)
    app.setApplicationName("StellaLog SNS Studio Public Demo")
    app.setOrganizationName("StellaLog")
    try:
        controller = StudioController()
        window = MainWindow(controller)
    except Exception as exc:
        QMessageBox.critical(
            None,
            "StellaLog SNS Studioを起動できませんでした",
            f"{exc}\n\n記事フォルダや保存先を確認してください。",
        )
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
