"""公開デモで、開発版の保存データや第三者素材を使わないことを検証。"""
from pathlib import Path

from stellalog_sns.models import AppSettings
from stellalog_sns.paths import app_data_dir, generated_videos_dir, voice_samples_dir
from stellalog_sns.settings import default_app_data_dir
from stellalog_sns.video_renderer import BACKGROUND_VIDEO_PATH, build_ffmpeg_command


def test_demo_data_stays_separate_from_development_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    expected = tmp_path / "StellaLogSNSStudio" / "public-demo"
    assert app_data_dir() == default_app_data_dir() == expected
    assert voice_samples_dir().parent == expected
    assert generated_videos_dir().parent == expected
    assert AppSettings().data_dir.name == "sample_data"
    assert AppSettings().site_origin == "https://example.invalid"


def test_public_video_needs_no_bgm_or_third_party_background(tmp_path):
    command = build_ffmpeg_command(
        ffmpeg_executable="ffmpeg",
        background_path=BACKGROUND_VIDEO_PATH,
        narration_path=tmp_path / "voice.wav",
        bgm_path=None,
        output_path=tmp_path / "result.mp4",
        duration_seconds=2.0,
        encoder="libx264",
    )
    graph = command[command.index("-filter_complex") + 1]
    assert "-loop" in command and "-stream_loop" not in command
    assert command.count("-i") == 3  # 自作背景、ナレーション、ロゴ
    assert "[2:v]scale=400:-1" in graph
    assert "amix=" not in graph and "delogo=" not in graph
    assert not any(Path(argument).suffix == ".mp3" for argument in command)
