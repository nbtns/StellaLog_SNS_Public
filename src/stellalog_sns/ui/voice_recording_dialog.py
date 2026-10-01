from __future__ import annotations

from io import BytesIO
from pathlib import Path
import wave

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QIODevice, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import (
    QAudio,
    QAudioDevice,
    QAudioFormat,
    QAudioOutput,
    QAudioSource,
    QMediaDevices,
    QMediaPlayer,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


VOICEBOX_MAX_SAMPLE_SECONDS = 29.0
VOICEBOX_REFERENCE_MAX_CHARS = 90


def voicebox_reference_excerpt(
    script: str,
    *,
    max_chars: int = VOICEBOX_REFERENCE_MAX_CHARS,
) -> str:
    """Return a short excerpt from the real script that fits a voice sample."""

    normalized = "\n".join(line.strip() for line in script.splitlines() if line.strip())
    if not normalized or len(normalized) <= max_chars:
        return normalized
    candidate = normalized[:max_chars]
    for separator in ("。", "！", "？", "!", "?"):
        position = candidate.rfind(separator)
        if position >= max_chars // 2:
            return candidate[: position + 1].strip()
    return candidate.rstrip("、，, ")


def wav_duration_seconds(path: Path | str) -> float | None:
    """Read a PCM WAV duration, returning None for an unreadable file."""

    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return wav_file.getnframes() / frame_rate
    except (OSError, EOFError, wave.Error):
        return None


def pcm_to_wav_bytes(
    pcm_data: bytes,
    *,
    sample_rate: int,
    channel_count: int,
    sample_width: int = 2,
) -> bytes:
    """Convert signed little-endian PCM samples to a standard WAV byte stream."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be greater than zero")
    if channel_count <= 0:
        raise ValueError("channel_count must be greater than zero")
    if sample_width not in (1, 2, 3, 4):
        raise ValueError("sample_width must be between 1 and 4 bytes")
    frame_size = channel_count * sample_width
    if len(pcm_data) % frame_size:
        raise ValueError("PCM data must contain complete audio frames")

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return output.getvalue()


def write_pcm_wav(
    destination: Path,
    pcm_data: bytes,
    *,
    sample_rate: int,
    channel_count: int,
    sample_width: int = 2,
) -> Path:
    """Write a WAV file atomically and return its final path."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f".{destination.name}.tmp")
    temporary_path.write_bytes(
        pcm_to_wav_bytes(
            pcm_data,
            sample_rate=sample_rate,
            channel_count=channel_count,
            sample_width=sample_width,
        )
    )
    temporary_path.replace(destination)
    return destination


class VoiceRecordingDialog(QDialog):
    """Record a local voice sample and let the user review it before accepting."""

    def __init__(
        self,
        destination_path: Path,
        recording_script: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("自分の声を録音")
        self.setMinimumSize(720, 620)
        self.resize(780, 680)

        self.destination_path = Path(destination_path)
        self.recording_script = voicebox_reference_excerpt(recording_script)
        self._accepted_path: Path | None = None
        self._audio_source: QAudioSource | None = None
        self._audio_device: QIODevice | None = None
        self._recording_format: QAudioFormat | None = None
        self._pcm_data = bytearray()
        self._elapsed = QElapsedTimer()
        self._stopped_automatically = False

        self._media_devices = QMediaDevices(self)
        self._media_devices.audioInputsChanged.connect(self.refresh_microphones)

        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._update_play_button)
        self._player.errorOccurred.connect(self._show_playback_error)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_elapsed_label)

        intro = QLabel(
            "今回のTikTok台本の冒頭から、Voicebox登録用に約30秒分を抜き出しています。\n"
            "静かな場所で、下に表示された部分だけを普段どおりの声で読んでください。"
        )
        intro.setWordWrap(True)

        self.recording_script_edit = QPlainTextEdit(self.recording_script)
        self.recording_script_edit.setObjectName("recordingScript")
        self.recording_script_edit.setReadOnly(True)
        self.recording_script_edit.setMinimumHeight(210)
        self.recording_script_edit.setStyleSheet(
            "QPlainTextEdit { background-color:#ffffff; color:#181818; "
            "border:2px solid #8d6bbd; border-radius:6px; padding:12px; "
            "font-size:16px; selection-background-color:#6f3cc3; "
            "selection-color:#ffffff; }"
        )

        self.microphone_combo = QComboBox()
        self.microphone_combo.setAccessibleName("録音に使うマイク")
        self.refresh_button = QPushButton("マイク一覧を更新")
        self.refresh_button.clicked.connect(self.refresh_microphones)
        self.permission_button = QPushButton("Windowsのマイク許可を開く")
        self.permission_button.clicked.connect(self.open_microphone_settings)
        microphone_row = QHBoxLayout()
        microphone_row.addWidget(QLabel("使うマイク:"))
        microphone_row.addWidget(self.microphone_combo, 1)
        microphone_row.addWidget(self.refresh_button)
        microphone_row.addWidget(self.permission_button)

        microphone_help = QLabel(
            "CABLE Outputは、CABLE Inputへ流した音を録音するための入力です。"
            "録音できないときは、音声を使うほかのアプリを終了してから"
            "「マイク一覧を更新」を押してください。"
        )
        microphone_help.setWordWrap(True)
        microphone_help.setStyleSheet("color:#d8d8d8;")

        self.elapsed_label = QLabel("00:00.0")
        self.elapsed_label.setObjectName("recordingTime")
        self.elapsed_label.setStyleSheet("font-size: 28px; font-weight: bold;")

        self.status_label = QLabel("マイクを選び、「録音を始める」を押してください。")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("recordingStatus")

        self.start_button = QPushButton("録音を始める")
        self.stop_button = QPushButton("録音を止める")
        self.play_button = QPushButton("録音を試聴")
        self.redo_button = QPushButton("録り直す")
        self.accept_button = QPushButton("この録音を採用")
        self.cancel_button = QPushButton("キャンセル")

        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)
        self.play_button.clicked.connect(self.toggle_playback)
        self.redo_button.clicked.connect(self.redo_recording)
        self.accept_button.clicked.connect(self.accept_recording)
        self.cancel_button.clicked.connect(self.reject)

        recording_buttons = QHBoxLayout()
        recording_buttons.addWidget(self.start_button)
        recording_buttons.addWidget(self.stop_button)
        recording_buttons.addWidget(self.play_button)
        recording_buttons.addWidget(self.redo_button)

        final_buttons = QHBoxLayout()
        final_buttons.addStretch()
        final_buttons.addWidget(self.cancel_button)
        final_buttons.addWidget(self.accept_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.recording_script_edit)
        layout.addLayout(microphone_row)
        layout.addWidget(microphone_help)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.status_label)
        layout.addLayout(recording_buttons)
        layout.addStretch()
        layout.addLayout(final_buttons)

        self.refresh_microphones()
        existing_duration = wav_duration_seconds(self.destination_path)
        has_compatible_recording = (
            existing_duration is not None
            and 0 < existing_duration <= VOICEBOX_MAX_SAMPLE_SECONDS
        )
        self._set_ready_state(has_recording=has_compatible_recording)
        if existing_duration is not None and not has_compatible_recording:
            self.status_label.setText(
                f"以前の録音は{existing_duration:.1f}秒で、Voiceboxの上限を超えています。"
                "「録音を始める」を押して録り直してください。29秒で自動停止します。"
            )

    def accepted_voice_path(self) -> Path | None:
        """Return the adopted WAV path after the dialog was accepted."""
        return self._accepted_path

    def accepted_reference_text(self) -> str:
        """Return the exact excerpt shown while recording."""

        return self.recording_script

    def refresh_microphones(self) -> None:
        selected_id = self.microphone_combo.currentData()
        self.microphone_combo.clear()
        devices = QMediaDevices.audioInputs()
        default_device = QMediaDevices.defaultAudioInput()
        selected_index = -1
        default_index = -1
        preferred_index = -1
        for index, device in enumerate(devices):
            device_id = bytes(device.id())
            label = device.description() or f"マイク {index + 1}"
            if self._is_preferred_input(label):
                label = f"{label}（使用する入力）"
                if preferred_index < 0:
                    preferred_index = index
            self.microphone_combo.addItem(label, device_id)
            if selected_id == device_id:
                selected_index = index
            if device == default_device:
                default_index = index
        if selected_index >= 0:
            self.microphone_combo.setCurrentIndex(selected_index)
        elif preferred_index >= 0:
            self.microphone_combo.setCurrentIndex(preferred_index)
        elif default_index >= 0:
            self.microphone_combo.setCurrentIndex(default_index)

        has_microphone = bool(devices)
        self.microphone_combo.setEnabled(has_microphone)
        if self._audio_source is None:
            self.start_button.setEnabled(has_microphone)
        if not has_microphone:
            self.status_label.setText(
                "マイクが見つかりません。Windowsの接続とマイクの使用許可を確認し、"
                "「マイク一覧を更新」を押してください。"
            )

    def open_microphone_settings(self) -> None:
        if QDesktopServices.openUrl(QUrl("ms-settings:privacy-microphone")):
            return
        QMessageBox.information(
            self,
            "Windowsのマイク設定",
            "Windowsの「設定」→「プライバシーとセキュリティ」→「マイク」を開いてください。",
        )

    def start_recording(self) -> None:
        if self._audio_source is not None:
            return
        device = self._selected_device()
        if device is None:
            QMessageBox.warning(
                self,
                "マイクを確認してください",
                "録音に使えるマイクが見つかりません。Windowsの設定を確認してください。",
            )
            return
        audio_format = self._supported_recording_format(device)
        if audio_format is None:
            QMessageBox.warning(
                self,
                "このマイクでは録音できません",
                "このマイクで使えるWAV録音形式を確認できませんでした。別のマイクを選んでください。",
            )
            return

        self._stop_playback()
        self._pcm_data.clear()
        self._stopped_automatically = False
        audio_device: QIODevice | None = None
        for attempt in range(2):
            candidate_input = device if attempt == 0 else self._selected_device()
            if candidate_input is None:
                break
            candidate_format = (
                audio_format
                if attempt == 0
                else self._supported_recording_format(candidate_input)
            )
            if candidate_format is None:
                break
            self._audio_source = QAudioSource(candidate_input, candidate_format, self)
            candidate_device = self._audio_source.start()
            if (
                candidate_device is not None
                and self._audio_source.error().value == QAudio.Error.NoError.value
            ):
                device = candidate_input
                audio_format = candidate_format
                audio_device = candidate_device
                break
            self._dispose_audio_source()
            QCoreApplication.processEvents()
            QThread.msleep(100)

        if self._audio_source is None or audio_device is None:
            device_name = device.description() or "選択したマイク"
            QMessageBox.warning(
                self,
                "録音を開始できません",
                f"「{device_name}」を開けませんでした。\n\n"
                "CABLE Outputを使っている録音・配信アプリを終了し、"
                "「マイク一覧を更新」を押してから、もう一度お試しください。\n\n"
                "Windowsのマイク許可もオンになっていることを確認してください。",
            )
            return

        self._audio_device = audio_device
        self._recording_format = audio_format
        self._audio_source.stateChanged.connect(self._recording_state_changed)
        self._audio_device.readyRead.connect(self._drain_audio)
        self._elapsed.start()
        self._timer.start()
        self.elapsed_label.setText("00:00.0")
        self.status_label.setText("録音中です。話し終わったら「録音を止める」を押してください。")
        self.microphone_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.play_button.setEnabled(False)
        self.redo_button.setEnabled(False)
        self.accept_button.setEnabled(False)

    def stop_recording(self) -> None:
        if self._audio_source is None:
            return
        self._drain_audio()
        self._audio_source.stop()
        self._timer.stop()
        audio_format = self._recording_format
        pcm_data = bytes(self._pcm_data)
        self._dispose_audio_source()

        if audio_format is None or not pcm_data:
            self.status_label.setText("音声を録音できませんでした。もう一度お試しください。")
            self._set_ready_state(has_recording=False)
            return
        frame_size = audio_format.channelCount() * 2
        max_frames = int(audio_format.sampleRate() * VOICEBOX_MAX_SAMPLE_SECONDS)
        pcm_data = pcm_data[: max_frames * frame_size]
        try:
            write_pcm_wav(
                self.destination_path,
                pcm_data,
                sample_rate=audio_format.sampleRate(),
                channel_count=audio_format.channelCount(),
                sample_width=2,
            )
        except OSError as error:
            self.status_label.setText("録音ファイルを保存できませんでした。保存先を確認してください。")
            QMessageBox.warning(self, "録音を保存できません", str(error))
            self._set_ready_state(has_recording=False)
            return

        if self._stopped_automatically:
            self.status_label.setText(
                "29秒になったため自動で録音を止めました。試聴して、問題なければ"
                "「この録音を採用」を押してください。"
            )
        else:
            self.status_label.setText(
                "録音できました。「録音を試聴」で確認し、問題なければ"
                "「この録音を採用」を押してください。"
            )
        self._set_ready_state(has_recording=True)

    def toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()
            return
        if not self.destination_path.is_file():
            return
        self._player.setSource(QUrl.fromLocalFile(str(self.destination_path.resolve())))
        self._player.play()

    def redo_recording(self) -> None:
        self._stop_playback()
        self._accepted_path = None
        self._pcm_data.clear()
        self.elapsed_label.setText("00:00.0")
        self.status_label.setText("マイクを選び、「録音を始める」を押してください。")
        self._set_ready_state(has_recording=False)

    def accept_recording(self) -> None:
        duration = wav_duration_seconds(self.destination_path)
        if duration is None or not (0 < duration <= VOICEBOX_MAX_SAMPLE_SECONDS):
            QMessageBox.warning(
                self,
                "30秒以内で録り直してください",
                "Voiceboxへ登録できる録音は30秒以内です。"
                "「録音を始める」を押して録り直してください。",
            )
            return
        self._stop_playback()
        self._accepted_path = self.destination_path
        self.accept()

    def reject(self) -> None:
        self._shutdown_audio()
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._shutdown_audio()
        super().closeEvent(event)

    def _selected_device(self) -> QAudioDevice | None:
        selected_id = self.microphone_combo.currentData()
        for device in QMediaDevices.audioInputs():
            if bytes(device.id()) == selected_id:
                return device
        return None

    @staticmethod
    def _is_preferred_input(description: str) -> bool:
        normalized = description.casefold()
        return "cable output" in normalized and "vb-audio" in normalized

    @staticmethod
    def _supported_recording_format(device: QAudioDevice) -> QAudioFormat | None:
        preferred_rate = device.preferredFormat().sampleRate()
        preferred_channels = device.preferredFormat().channelCount()
        candidates = [
            (48_000, 1),
            (44_100, 1),
            (preferred_rate, 1),
            (preferred_rate, preferred_channels),
        ]
        seen: set[tuple[int, int]] = set()
        for sample_rate, channel_count in candidates:
            if sample_rate <= 0 or channel_count <= 0 or (sample_rate, channel_count) in seen:
                continue
            seen.add((sample_rate, channel_count))
            audio_format = QAudioFormat()
            audio_format.setSampleRate(sample_rate)
            audio_format.setChannelCount(channel_count)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if device.isFormatSupported(audio_format):
                return audio_format
        return None

    def _drain_audio(self) -> None:
        if self._audio_device is not None:
            self._pcm_data.extend(bytes(self._audio_device.readAll()))

    def _recording_state_changed(self, state: QAudio.State) -> None:
        if (
            self._audio_source is not None
            and state.value == QAudio.State.StoppedState.value
            and self._audio_source.error().value != QAudio.Error.NoError.value
        ):
            self._timer.stop()
            self.status_label.setText(
                "録音が途中で止まりました。マイクの接続とWindowsの使用許可を確認してください。"
            )
            self._dispose_audio_source()
            self._set_ready_state(has_recording=self.destination_path.is_file())

    def _update_elapsed_label(self) -> None:
        elapsed_ms = max(0, self._elapsed.elapsed())
        minutes, remainder = divmod(elapsed_ms, 60_000)
        seconds, tenths_ms = divmod(remainder, 1_000)
        self.elapsed_label.setText(f"{minutes:02d}:{seconds:02d}.{tenths_ms // 100}")
        if elapsed_ms >= int(VOICEBOX_MAX_SAMPLE_SECONDS * 1_000):
            self._stopped_automatically = True
            self.stop_recording()

    def _update_play_button(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("試聴を止める")
        else:
            self.play_button.setText("録音を試聴")

    def _show_playback_error(self, _error, error_string: str) -> None:  # type: ignore[no-untyped-def]
        if error_string:
            self.status_label.setText("録音を再生できませんでした。録り直してもう一度お試しください。")

    def _set_ready_state(self, *, has_recording: bool) -> None:
        is_recording = self._audio_source is not None
        has_microphone = self.microphone_combo.count() > 0
        self.microphone_combo.setEnabled(not is_recording and has_microphone)
        self.refresh_button.setEnabled(not is_recording)
        self.start_button.setEnabled(not is_recording and has_microphone)
        self.stop_button.setEnabled(is_recording)
        self.play_button.setEnabled(not is_recording and has_recording)
        self.redo_button.setEnabled(not is_recording and has_recording)
        self.accept_button.setEnabled(not is_recording and has_recording)

    def _stop_playback(self) -> None:
        self._player.stop()
        # Windowsでは停止だけではWAVのファイルハンドルが残ることがある。
        # 空の再生元へ切り替えてからイベントを処理し、録り直し時の上書きを可能にする。
        self._player.setSource(QUrl())
        QCoreApplication.processEvents()

    def _dispose_audio_source(self) -> None:
        if self._audio_source is not None:
            self._audio_source.deleteLater()
        self._audio_source = None
        self._audio_device = None
        self._recording_format = None

    def _shutdown_audio(self) -> None:
        self._timer.stop()
        self._stop_playback()
        if self._audio_source is not None:
            self._audio_source.stop()
        self._dispose_audio_source()
