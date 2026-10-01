"""画面を固めずにローカルの重い処理を行う小さなワーカー。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class BackgroundTask(QThread):
    succeeded = Signal(object)
    failed = Signal(object)
    progressed = Signal(int, str)

    def __init__(
        self,
        function: Callable[..., Any],
        parent=None,
        *,
        with_progress: bool = False,
    ) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self._function = function
        self._with_progress = with_progress

    def run(self) -> None:
        try:
            if self._with_progress:
                result = self._function(self.report_progress)
            else:
                result = self._function()
        except Exception as exc:  # 画面側で日本語エラーとして表示する
            self.failed.emit(exc)
            return
        self.succeeded.emit(result)

    def report_progress(self, percent: int, message: str) -> None:
        """Send worker progress safely to widgets on the main thread."""

        self.progressed.emit(percent, message)
