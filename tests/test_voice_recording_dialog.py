from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from stellalog_sns.ui.voice_recording_dialog import (
    VOICEBOX_MAX_SAMPLE_SECONDS,
    VoiceRecordingDialog,
    pcm_to_wav_bytes,
    voicebox_reference_excerpt,
    wav_duration_seconds,
    write_pcm_wav,
)


def test_pcm_to_wav_bytes_creates_valid_pcm_header() -> None:
    pcm_data = bytes.fromhex("0000 ff7f 0080 0000")

    wav_data = pcm_to_wav_bytes(
        pcm_data,
        sample_rate=48_000,
        channel_count=1,
        sample_width=2,
    )

    assert wav_data[:4] == b"RIFF"
    assert wav_data[8:12] == b"WAVE"
    with wave.open(BytesIO(wav_data), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 48_000
        assert wav_file.getnframes() == 4
        assert wav_file.readframes(4) == pcm_data


def test_pcm_to_wav_bytes_rejects_incomplete_audio_frame() -> None:
    with pytest.raises(ValueError, match="complete audio frames"):
        pcm_to_wav_bytes(
            b"\x00\x01\x02",
            sample_rate=44_100,
            channel_count=2,
            sample_width=2,
        )


def test_write_pcm_wav_creates_parent_folder(tmp_path: Path) -> None:
    destination = tmp_path / "voice" / "sample.wav"

    result = write_pcm_wav(
        destination,
        b"\x00\x00" * 10,
        sample_rate=44_100,
        channel_count=1,
    )

    assert result == destination
    assert destination.read_bytes().startswith(b"RIFF")
    assert not destination.with_name(f".{destination.name}.tmp").exists()


def test_dialog_initial_state_does_not_require_a_real_microphone(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    destination = tmp_path / "voice-samples" / "my-voice.wav"

    recording_script = "これは実際に作成されたTikTok動画の台本です。" * 12
    dialog = VoiceRecordingDialog(destination, recording_script)

    assert dialog.windowTitle() == "自分の声を録音"
    assert dialog.destination_path == destination
    assert dialog.elapsed_label.text() == "00:00.0"
    assert not dialog.stop_button.isEnabled()
    assert not dialog.play_button.isEnabled()
    assert not dialog.redo_button.isEnabled()
    assert not dialog.accept_button.isEnabled()
    assert dialog.accepted_voice_path() is None
    assert "マイク" in dialog.status_label.text()
    assert dialog.recording_script_edit.toPlainText() == voicebox_reference_excerpt(
        recording_script
    )
    assert dialog.accepted_reference_text() == dialog.recording_script_edit.toPlainText()
    assert "background-color:#ffffff" in dialog.recording_script_edit.styleSheet()
    assert "color:#181818" in dialog.recording_script_edit.styleSheet()
    assert dialog.permission_button.text() == "Windowsのマイク許可を開く"

    dialog.close()
    app.processEvents()


def test_dialog_can_adopt_an_existing_recording(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    destination = write_pcm_wav(
        tmp_path / "voice-samples" / "my-voice.wav",
        b"\x00\x00" * 10,
        sample_rate=44_100,
        channel_count=1,
    )
    dialog = VoiceRecordingDialog(destination, "実際のTikTok台本")

    assert dialog.play_button.isEnabled()
    assert dialog.redo_button.isEnabled()
    assert dialog.accept_button.isEnabled()

    dialog.accept_recording()

    assert dialog.accepted_voice_path() == destination
    assert dialog.result() == VoiceRecordingDialog.DialogCode.Accepted
    dialog.close()
    app.processEvents()


def test_long_existing_recording_must_be_recorded_again(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    sample_rate = 100
    destination = write_pcm_wav(
        tmp_path / "voice-samples" / "too-long.wav",
        b"\x00\x00" * int(sample_rate * (VOICEBOX_MAX_SAMPLE_SECONDS + 2)),
        sample_rate=sample_rate,
        channel_count=1,
    )

    dialog = VoiceRecordingDialog(destination, "実際のTikTok台本")

    assert wav_duration_seconds(destination) == VOICEBOX_MAX_SAMPLE_SECONDS + 2
    assert not dialog.accept_button.isEnabled()
    assert "上限を超えています" in dialog.status_label.text()

    dialog.close()
    app.processEvents()


def test_reference_excerpt_comes_from_real_script_and_stays_short() -> None:
    script = "最初の文章です。" + "これは実際のTikTok台本です。" * 20

    excerpt = voicebox_reference_excerpt(script, max_chars=90)

    assert script.startswith(excerpt)
    assert len(excerpt) <= 90
    assert excerpt.endswith("。")


def test_redo_releases_the_playback_file_before_overwriting(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    destination = write_pcm_wav(
        tmp_path / "voice-samples" / "redo.wav",
        b"\x00\x00" * 1_000,
        sample_rate=44_100,
        channel_count=1,
    )
    dialog = VoiceRecordingDialog(destination, "録り直し用のTikTok台本")

    dialog.toggle_playback()
    app.processEvents()
    dialog.redo_recording()

    assert dialog._player.source().isEmpty()
    result = write_pcm_wav(
        destination,
        b"\x01\x00" * 1_000,
        sample_rate=44_100,
        channel_count=1,
    )
    assert result == destination
    assert destination.read_bytes().startswith(b"RIFF")

    dialog.close()
    app.processEvents()


def test_vb_audio_cable_output_is_preferred() -> None:
    assert VoiceRecordingDialog._is_preferred_input(
        "CABLE Output (VB-Audio Virtual Cable)"
    )
    assert not VoiceRecordingDialog._is_preferred_input("Line (AG06/AG03)")
    assert not VoiceRecordingDialog._is_preferred_input("Microphone Array")
