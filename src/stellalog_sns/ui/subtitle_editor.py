"""字幕カードごとに表示と読みを確認・編集するウィジェット。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..paths import app_data_dir
from ..video_renderer import (
    BACKGROUND_VIDEO_PATH,
    SUBTITLE_CENTER_X,
    SUBTITLE_CENTER_Y,
    SUBTITLE_FONT_FAMILY,
    SUBTITLE_FONT_PATH,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_OUTLINE_THICKNESS,
    SUBTITLE_SOFT_OUTLINE_BLUR,
    SUBTITLE_TEXT_COLOR,
    VIDEO_HEIGHT,
    VIDEO_LOGO_PATH,
    VIDEO_WIDTH,
    VideoRenderError,
    split_subtitle_cards,
)


_CARD_SEPARATOR = "\n\n"


class SubtitlePreview(QWidget):
    """完成動画と同じ座標系で字幕・ロゴを描く縦型プレビュー。"""

    _font_id: int | None = None

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        logo_path: Path | str = VIDEO_LOGO_PATH,
        font_path: Path | str = SUBTITLE_FONT_PATH,
    ) -> None:
        super().__init__(parent)
        self._lines: tuple[str, ...] = ()
        self._background = QImage()
        self._logo = QImage(str(Path(logo_path)))
        self._font_path = Path(font_path)
        self.setMinimumSize(135, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("選択した字幕カードの縦型プレビュー")

    def sizeHint(self) -> QSize:
        return QSize(270, 480)

    def set_lines(self, lines: tuple[str, ...]) -> None:
        self._lines = tuple(line.replace("、", "") for line in lines)
        self.update()

    def set_background_image(self, image: QImage) -> None:
        self._background = image.copy()
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        target = self._video_rect()
        painter.fillRect(self.rect(), QColor("#17131f"))
        if self._background.isNull():
            gradient = QLinearGradient(target.topLeft(), target.bottomRight())
            gradient.setColorAt(0.0, QColor("#160922"))
            gradient.setColorAt(0.5, QColor("#35104f"))
            gradient.setColorAt(1.0, QColor("#09030f"))
            painter.fillRect(target, gradient)
        else:
            painter.drawImage(target, self._background)

        painter.save()
        painter.setClipRect(target)
        painter.translate(target.left(), target.top())
        scale = target.width() / VIDEO_WIDTH
        painter.scale(scale, scale)
        self._draw_logo(painter)
        self._draw_subtitle(painter)
        painter.restore()

        painter.setPen(QPen(QColor("#7e748b"), 1))
        painter.drawRect(target.adjusted(0, 0, -1, -1))
        painter.end()

    def _video_rect(self) -> QRectF:
        available = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        width = min(available.width(), available.height() * VIDEO_WIDTH / VIDEO_HEIGHT)
        height = width * VIDEO_HEIGHT / VIDEO_WIDTH
        if height > available.height():
            height = available.height()
            width = height * VIDEO_WIDTH / VIDEO_HEIGHT
        return QRectF(
            available.center().x() - width / 2,
            available.center().y() - height / 2,
            width,
            height,
        )

    def _draw_logo(self, painter: QPainter) -> None:
        if self._logo.isNull() or self._logo.width() <= 0:
            return
        logo_width = 400.0
        logo_height = logo_width * self._logo.height() / self._logo.width()
        target = QRectF(
            (VIDEO_WIDTH - logo_width) / 2,
            VIDEO_HEIGHT - logo_height - 40,
            logo_width,
            logo_height,
        )
        painter.drawImage(target, self._logo)

    def _draw_subtitle(self, painter: QPainter) -> None:
        visible_lines = tuple(line for line in self._lines if line)
        if not visible_lines:
            return
        self._load_font()
        font = QFont(SUBTITLE_FONT_FAMILY)
        font.setPixelSize(SUBTITLE_FONT_SIZE)
        metrics = QFontMetricsF(font)
        # ASSのFontsizeはフォントの行高を基準にする。Qtのemサイズのままだと
        # 日本語の字面が大きくなり、完成動画では収まる字幕がはみ出す。
        font.setPixelSize(max(1, round(SUBTITLE_FONT_SIZE * SUBTITLE_FONT_SIZE / metrics.height())))
        metrics = QFontMetricsF(font)
        line_step = metrics.height() * 1.02

        paths: list[QPainterPath] = []
        block_bounds = QRectF()
        for index, line in enumerate(visible_lines):
            path = QPainterPath()
            path.addText(0, index * line_step + metrics.ascent(), font, line)
            paths.append(path)
            block_bounds = block_bounds.united(path.boundingRect())
        y_shift = SUBTITLE_CENTER_Y - block_bounds.center().y()

        for path in paths:
            bounds = path.boundingRect()
            x_shift = SUBTITLE_CENTER_X - bounds.center().x()
            positioned = path.translated(x_shift, y_shift)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(
                QPen(
                    QColor(0, 0, 0, 105),
                    (
                        SUBTITLE_OUTLINE_THICKNESS
                        + SUBTITLE_SOFT_OUTLINE_BLUR
                    )
                    * 2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(positioned)
            painter.setPen(
                QPen(
                    QColor("#000000"),
                    SUBTITLE_OUTLINE_THICKNESS * 2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(positioned)
            # 太い縁取りの後に文字の内側を塗り、黒い輪郭に埋もれないようにする。
            painter.fillPath(positioned, QColor(SUBTITLE_TEXT_COLOR))

    def _load_font(self) -> None:
        if SubtitlePreview._font_id is None:
            SubtitlePreview._font_id = QFontDatabase.addApplicationFont(
                str(self._font_path)
            )


class SubtitleEditor(QWidget):
    """字幕と音声用の読みを、対応するカード単位で編集する。"""

    scriptsChanged = Signal(str, str)
    previewRequested = Signal(int)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        background_video_path: Path | str = BACKGROUND_VIDEO_PATH,
        logo_path: Path | str = VIDEO_LOGO_PATH,
        font_path: Path | str = SUBTITLE_FONT_PATH,
        ffmpeg_executable: str = "ffmpeg",
        auto_load_preview: bool = True,
    ) -> None:
        super().__init__(parent)
        self._subtitle_script = ""
        self._narration_script = ""
        self._subtitle_cards: tuple[str, ...] = ()
        self._narration_cards: tuple[str, ...] = ()
        self._preview_cards: tuple[tuple[str, ...], ...] = ()
        self._updating_ui = False
        self._busy = False
        self._valid = True
        self._pending_invalid = False
        self._validation_message = ""
        self._background_video_path = Path(background_video_path)
        self._ffmpeg_executable = ffmpeg_executable
        self._frame_process: QProcess | None = None

        self._build_ui(logo_path=logo_path, font_path=font_path)
        self._connect_signals()
        self._refresh_enabled_state()
        if auto_load_preview:
            self._load_background_frame()

    def _build_ui(self, *, logo_path: Path | str, font_path: Path | str) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        help_label = QLabel(
            "左で字幕カードを選び、中央で字幕と音声用の読みを直します。"
            "通常の改行は同じカード内、空白行はカードの切り替えです。"
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color:#505766;")
        outer.addWidget(help_label)

        self.validation_label = QLabel()
        self.validation_label.setWordWrap(True)
        self.validation_label.setVisible(False)
        self.validation_label.setStyleSheet(
            "color:#9b2c2c; background:#fff3f3; border:1px solid #e7b7b7;"
            "border-radius:4px; padding:5px;"
        )
        outer.addWidget(self.validation_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        list_panel = QFrame()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 6, 0)
        list_layout.addWidget(QLabel("字幕カード"))
        self.card_list = QListWidget()
        self.card_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.card_list.setMinimumWidth(170)
        self.card_list.setMaximumWidth(250)
        self.card_list.setAccessibleName("字幕カード一覧")
        list_layout.addWidget(self.card_list, 1)
        self.card_position_label = QLabel("0 / 0")
        self.card_position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_layout.addWidget(self.card_position_label)
        splitter.addWidget(list_panel)

        edit_panel = QFrame()
        edit_layout = QVBoxLayout(edit_panel)
        edit_layout.setContentsMargins(6, 0, 6, 0)
        edit_layout.setSpacing(5)
        edit_layout.addWidget(QLabel("動画に表示する字幕"))
        self.subtitle_edit = QPlainTextEdit()
        self.subtitle_edit.setPlaceholderText("選択したカードの字幕")
        self.subtitle_edit.setTabChangesFocus(True)
        self.subtitle_edit.setAccessibleName("選択したカードの字幕")
        edit_layout.addWidget(self.subtitle_edit, 1)
        narration_label = QLabel("VOICEVOXに読ませる文字")
        narration_label.setToolTip("ここを直しても、動画に表示する字幕は変わりません。")
        edit_layout.addWidget(narration_label)
        self.narration_edit = QPlainTextEdit()
        self.narration_edit.setPlaceholderText("選択したカードの音声用の読み")
        self.narration_edit.setTabChangesFocus(True)
        self.narration_edit.setAccessibleName("選択したカードの音声用の読み")
        edit_layout.addWidget(self.narration_edit, 1)
        self.preview_audio_button = QPushButton("このカードの音声を確認")
        self.preview_audio_button.setToolTip(
            "選択中のカードだけをVOICEVOXで作成して再生します。"
        )
        edit_layout.addWidget(self.preview_audio_button)
        splitter.addWidget(edit_panel)

        preview_panel = QFrame()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(6, 0, 0, 0)
        preview_layout.setSpacing(4)
        preview_layout.addWidget(QLabel("完成イメージ"))
        self.preview = SubtitlePreview(
            logo_path=logo_path,
            font_path=font_path,
        )
        preview_layout.addWidget(self.preview, 1)
        self.background_status_label = QLabel("実際の背景を準備しています…")
        self.background_status_label.setWordWrap(True)
        self.background_status_label.setStyleSheet("color:#505766; font-size:11px;")
        preview_layout.addWidget(self.background_status_label)
        approximation = QLabel(
            "字幕の位置・大きさ・色は完成動画と同じ設定です。"
            "文字の形・行間・縁のぼかしはQtによる近似表示です。"
        )
        approximation.setWordWrap(True)
        approximation.setStyleSheet("color:#6b6174; font-size:11px;")
        preview_layout.addWidget(approximation)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, 1)

    def _connect_signals(self) -> None:
        self.card_list.currentRowChanged.connect(self._select_card)
        self.subtitle_edit.textChanged.connect(self._subtitle_edited)
        self.narration_edit.textChanged.connect(self._narration_edited)
        self.preview_audio_button.clicked.connect(self._request_audio_preview)

    def set_scripts(self, subtitle_script: str, narration_script: str) -> None:
        """全文タブの内容を反映する。呼び出し自体では変更Signalを出さない。"""

        subtitle = _normalise_line_endings(subtitle_script)
        narration = _normalise_line_endings(narration_script)
        if subtitle == self._subtitle_script and narration == self._narration_script:
            return
        previous_row = self.card_list.currentRow()
        self._subtitle_script = subtitle
        self._narration_script = narration
        self._pending_invalid = False

        subtitle_cards, subtitle_error = _parse_cards(subtitle, "字幕")
        narration_cards, narration_error = _parse_cards(narration, "音声用の読み")
        error = subtitle_error or narration_error
        if not error and len(subtitle_cards) != len(narration_cards):
            error = (
                f"字幕は{len(subtitle_cards)}枚、音声用の読みは{len(narration_cards)}枚です。"
                "全文タブで空白行の位置をそろえてください。カード数は自動変更しません。"
            )
        preview_cards: list[tuple[str, ...]] = []
        if not error:
            for index, (subtitle_card, _narration_card) in enumerate(
                zip(subtitle_cards, narration_cards, strict=True)
            ):
                subtitle_lines, card_error = _rendered_card_lines(
                    subtitle_card,
                    label="字幕",
                    card_number=index + 1,
                )
                if card_error:
                    error = card_error
                    break
                preview_cards.append(subtitle_lines)

        self._valid = not error
        self._validation_message = error
        self._subtitle_cards = subtitle_cards if self._valid else ()
        self._narration_cards = narration_cards if self._valid else ()
        self._preview_cards = tuple(preview_cards) if self._valid else ()
        self._populate_card_list(previous_row)
        self._show_validation(error)
        self._refresh_enabled_state()

    def scripts(self) -> tuple[str, str]:
        return self._subtitle_script, self._narration_script

    def pending_scripts(self) -> tuple[str, str]:
        """未確定の入力も含め、画面に現在見えている全文を返す。"""

        if not self._pending_invalid:
            return self.scripts()
        row = self.card_list.currentRow()
        if not 0 <= row < len(self._subtitle_cards):
            return self.scripts()
        subtitle_cards = list(self._subtitle_cards)
        narration_cards = list(self._narration_cards)
        subtitle_cards[row] = _normalise_line_endings(self.subtitle_edit.toPlainText())
        narration_cards[row] = _normalise_line_endings(self.narration_edit.toPlainText())
        return _CARD_SEPARATOR.join(subtitle_cards), _CARD_SEPARATOR.join(narration_cards)

    def has_pending_edits(self) -> bool:
        return self.pending_scripts() != self.scripts()

    def subtitle_script(self) -> str:
        return self._subtitle_script

    def narration_script(self) -> str:
        return self._narration_script

    def card_count(self) -> int:
        return len(self._subtitle_cards)

    def current_card_index(self) -> int:
        return self.card_list.currentRow()

    def is_valid(self) -> bool:
        return self._valid and not self._pending_invalid

    def validation_message(self) -> str:
        return self._validation_message

    def select_card(self, index: int) -> None:
        if 0 <= index < self.card_list.count() and not self._pending_invalid:
            self.card_list.setCurrentRow(index)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._refresh_enabled_state()

    def _populate_card_list(self, preferred_row: int) -> None:
        self._updating_ui = True
        try:
            self.card_list.clear()
            for index, card in enumerate(self._subtitle_cards):
                item = QListWidgetItem(_card_title(index, card))
                item.setToolTip(card.replace("、", ""))
                self.card_list.addItem(item)
            if self.card_list.count():
                row = min(max(preferred_row, 0), self.card_list.count() - 1)
                self.card_list.setCurrentRow(row)
                self._display_card(row)
            else:
                self._clear_card_fields()
        finally:
            self._updating_ui = False

    def _select_card(self, row: int) -> None:
        if self._updating_ui:
            return
        self._display_card(row)

    def _display_card(self, row: int) -> None:
        self._updating_ui = True
        try:
            if not 0 <= row < len(self._subtitle_cards):
                self._clear_card_fields()
                return
            if self.subtitle_edit.toPlainText() != self._subtitle_cards[row]:
                self.subtitle_edit.setPlainText(self._subtitle_cards[row])
            if self.narration_edit.toPlainText() != self._narration_cards[row]:
                self.narration_edit.setPlainText(self._narration_cards[row])
            self.preview.set_lines(self._preview_cards[row])
            self.card_position_label.setText(f"{row + 1} / {len(self._subtitle_cards)}")
        finally:
            self._updating_ui = False

    def _clear_card_fields(self) -> None:
        self.subtitle_edit.clear()
        self.narration_edit.clear()
        self.preview.set_lines(())
        self.card_position_label.setText(f"0 / {len(self._subtitle_cards)}")

    def _subtitle_edited(self) -> None:
        self._apply_card_edit(is_subtitle=True)

    def _narration_edited(self) -> None:
        self._apply_card_edit(is_subtitle=False)

    def _apply_card_edit(self, *, is_subtitle: bool) -> None:
        if self._updating_ui:
            return
        row = self.card_list.currentRow()
        if not 0 <= row < len(self._subtitle_cards):
            return
        editor = self.subtitle_edit if is_subtitle else self.narration_edit
        value = _normalise_line_endings(editor.toPlainText())
        label = "字幕" if is_subtitle else "音声用の読み"
        _cards, error = _parse_cards(value, label)
        if error or _CARD_SEPARATOR in value:
            self._pending_invalid = True
            self._validation_message = (
                error
                or "カード内に空白行は入れられません。カードの増減は全文タブで、字幕と読みを一緒に直してください。"
            )
            self._show_validation(self._validation_message)
            self._refresh_enabled_state()
            return
        preview_lines: tuple[str, ...] = ()
        if is_subtitle:
            preview_lines, render_error = _rendered_card_lines(
                value,
                label=label,
                card_number=row + 1,
            )
            if render_error:
                self._pending_invalid = True
                self._validation_message = render_error
                self._show_validation(render_error)
                self._refresh_enabled_state()
                return

        subtitle_cards = list(self._subtitle_cards)
        narration_cards = list(self._narration_cards)
        preview_cards = list(self._preview_cards)
        target_cards = subtitle_cards if is_subtitle else narration_cards
        if target_cards[row] == value:
            self._pending_invalid = False
            self._validation_message = ""
            self._show_validation("")
            self._refresh_enabled_state()
            return
        target_cards[row] = value
        self._subtitle_cards = tuple(subtitle_cards)
        self._narration_cards = tuple(narration_cards)
        if is_subtitle:
            preview_cards[row] = preview_lines
        self._preview_cards = tuple(preview_cards)
        self._subtitle_script = _CARD_SEPARATOR.join(self._subtitle_cards)
        self._narration_script = _CARD_SEPARATOR.join(self._narration_cards)
        self._pending_invalid = False
        self._validation_message = ""
        self._show_validation("")
        if is_subtitle:
            self.preview.set_lines(preview_lines)
            item = self.card_list.item(row)
            if item is not None:
                item.setText(_card_title(row, value))
                item.setToolTip(value.replace("、", ""))
        self._refresh_enabled_state()
        self.scriptsChanged.emit(self._subtitle_script, self._narration_script)

    def _request_audio_preview(self) -> None:
        row = self.card_list.currentRow()
        if self.is_valid() and not self._busy and 0 <= row < self.card_count():
            self.previewRequested.emit(row)

    def _show_validation(self, message: str) -> None:
        self.validation_label.setText(message)
        self.validation_label.setVisible(bool(message))

    def _refresh_enabled_state(self) -> None:
        editable = self._valid and bool(self._subtitle_cards) and not self._busy
        self.card_list.setEnabled(editable and not self._pending_invalid)
        self.subtitle_edit.setEnabled(editable)
        self.narration_edit.setEnabled(editable)
        self.preview_audio_button.setEnabled(editable and not self._pending_invalid)

    def _load_background_frame(self) -> None:
        source = self._background_video_path
        if not source.is_file():
            self.background_status_label.setText(
                "動画用の背景が見つからないため、背景だけ簡易表示です。"
            )
            return
        if source.suffix.lower() == ".png":
            image = QImage(str(source))
            if not image.isNull():
                self.preview.set_background_image(image)
                self.background_status_label.setText("コードで描いた星空背景を表示しています。")
            else:
                self.background_status_label.setText("背景画像を読み込めないため、背景だけ簡易表示です。")
            return
        cache_path = app_data_dir() / "preview_cache" / "background-frame-v3.png"
        if _cache_is_current(cache_path, source):
            image = QImage(str(cache_path))
            if not image.isNull():
                self.preview.set_background_image(image)
                self.background_status_label.setText("実際の背景フレームを表示しています。")
                return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.background_status_label.setText(
                "背景の一時画像を保存できないため、背景だけ簡易表示です。"
            )
            return

        process = QProcess(self)
        self._frame_process = process
        process.finished.connect(
            lambda exit_code, _status: self._background_frame_finished(
                exit_code, cache_path
            )
        )
        process.errorOccurred.connect(self._background_frame_error)
        process.start(
            self._ffmpeg_executable,
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "0",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                "scale=540:960",
                str(cache_path),
            ],
        )

    def _background_frame_finished(self, exit_code: int, cache_path: Path) -> None:
        self._frame_process = None
        image = QImage(str(cache_path)) if exit_code == 0 else QImage()
        if image.isNull():
            self.background_status_label.setText(
                "背景フレームを読み込めないため、背景だけ簡易表示です。"
            )
            return
        self.preview.set_background_image(image)
        self.background_status_label.setText("実際の背景フレームを表示しています。")

    def _background_frame_error(self, _error: QProcess.ProcessError) -> None:
        self.background_status_label.setText(
            "FFmpegで背景を読み込めないため、背景だけ簡易表示です。"
        )


def _normalise_line_endings(value: str) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _parse_cards(script: str, label: str) -> tuple[tuple[str, ...], str]:
    if not script:
        return (), ""
    lines = script.split("\n")
    if not lines[0] or not lines[-1]:
        return (), f"{label}の先頭または末尾に空の行があります。空白行の位置を確認してください。"
    if any(line and not line.strip() for line in lines):
        return (), f"{label}に空白文字だけの行があります。空白行には文字を入れないでください。"
    cards = script.split(_CARD_SEPARATOR)
    if any(not card or card.startswith("\n") or card.endswith("\n") for card in cards):
        return (), f"{label}に空のカードがあります。空白行はカード間に1行だけ入れてください。"
    if any(any(not line for line in card.split("\n")) for card in cards):
        return (), f"{label}に空の行があります。空白行はカードの切り替えにだけ使ってください。"
    return tuple(cards), ""


def _rendered_card_lines(
    card: str,
    *,
    label: str,
    card_number: int,
) -> tuple[tuple[str, ...], str]:
    try:
        rendered_cards = split_subtitle_cards(
            card,
        )
    except (ValueError, VideoRenderError) as exc:
        return (), str(exc)
    if len(rendered_cards) != 1:
        return (), (
            f"{card_number}枚目の{label}は、完成動画では{len(rendered_cards)}枚に"
            "自動分割されます。全文タブで行を短くし、字幕と読みの空白行を"
            "同じ位置に追加してください。音声確認は内容を直すまで利用できません。"
        )
    return rendered_cards[0], ""


def _card_title(index: int, card: str) -> str:
    visible = " ".join(line.replace("、", "").strip() for line in card.split("\n"))
    summary = visible if len(visible) <= 18 else visible[:18] + "…"
    return f"{index + 1}枚目  {summary}"


def _cache_is_current(cache_path: Path, source_path: Path) -> bool:
    try:
        return cache_path.is_file() and cache_path.stat().st_mtime >= source_path.stat().st_mtime
    except OSError:
        return False
