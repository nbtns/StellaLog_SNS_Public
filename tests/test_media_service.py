from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import wave

import pytest

from stellalog_sns.media_service import (
    MediaService,
    _concatenate_pcm_wavs,
    narration_text,
    resolve_stellalog_logo,
)
from stellalog_sns.models import AppSettings, Article, PostSet
from stellalog_sns.video_renderer import VideoRenderResult
from stellalog_sns.voice_services import (
    NarrationResult,
    VoiceProfile,
    VoiceServiceError,
)


def _post(tmp_path: Path) -> PostSet:
    article = Article(
        article_key="love/female/enfj/aquarius",
        concern="love",
        gender="female",
        mbti="enfj",
        zodiac="aquarius",
        title="恋愛傾向",
        content=(),
        sns_catchphrase="",
        source_path=tmp_path / "article.json",
    )
    return PostSet(
        article=article,
        selected_at=datetime(2026, 9, 1, 12, 0),
        tiktok_script="ENFJと水瓶座の本当の恋愛傾向",
        x_post="X投稿",
        canonical_url="https://example.test/article",
        tiktok_url="https://example.test/article?utm_source=tiktok",
        x_url="https://example.test/article?utm_source=x",
        hashtags=("#MBTI",),
        tiktok_template_id="tiktok_question_opening",
        x_template_id="x_relatable",
        source_points=(),
        estimated_tiktok_seconds=65,
        x_weighted_length=10,
    )


def test_resolve_logo_uses_read_only_stellalog_public_folder(tmp_path: Path) -> None:
    data_dir = tmp_path / "web" / "src" / "data"
    logo = tmp_path / "web" / "public" / "stellalog_logo3-4.png"
    data_dir.mkdir(parents=True)
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"png")

    assert resolve_stellalog_logo(data_dir) == logo


def test_narration_text_adds_pauses_and_pronunciation_readings() -> None:
    result = narration_text("ENFJ×水瓶座\n詳しい続きは「StellaLog」で検索してね")

    assert result == "イーエヌエフジェイと水瓶座。詳しい続きは「ステラログ」で検索してね。"


def test_narration_text_applies_pronunciation_corrections_only_to_voice_text() -> None:
    script = "仕事が辛くなる\n快と不快の境界\n一途さと金星星座\n口を開く"

    result = narration_text(script)

    assert script == "仕事が辛くなる\n快と不快の境界\n一途さと金星星座\n口を開く"
    assert result == (
        "仕事がつらくなる。かいと不快の境界。いちずさときんせいせいざ。"
        "くちを開く。"
    )


def test_register_voice_reuses_profile_with_same_name(tmp_path: Path) -> None:
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"RIFF....WAVE")
    service = MediaService(AppSettings(voicebox_profile_name="StellaLog"))
    profile = VoiceProfile("profile-1", "StellaLog")
    calls: list[tuple[str, Path, str]] = []

    class FakeVoicebox:
        def list_profiles(self):
            return [profile]

        def create_profile(self, *args, **kwargs):
            raise AssertionError("既存プロファイルを再利用する")

        def add_sample(self, profile_id, wav_path, reference_text):
            calls.append((profile_id, Path(wav_path), reference_text))

    service.voicebox = FakeVoicebox()  # type: ignore[assignment]

    result = service.register_voice_sample(sample, "録音した文章")

    assert result == profile
    assert calls == [("profile-1", sample, "録音した文章")]


def test_generate_video_passes_narration_to_renderer(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "web" / "src" / "data"
    data_dir.mkdir(parents=True)
    output = tmp_path / "finished.mp4"
    received: dict[str, object] = {}

    class FakeRenderer:
        def render(
            self,
            script,
            narration,
            destination,
            *,
            subtitle_cards=None,
            subtitle_durations=None,
        ):
            received.update(
                script=script,
                narration=Path(narration),
                destination=Path(destination),
                subtitle_cards=subtitle_cards,
                subtitle_durations=subtitle_durations,
            )
            Path(destination).write_bytes(b"video")
            return VideoRenderResult(Path(destination), 65.0, "h264_nvenc")

    service = MediaService(
        AppSettings(data_dir=data_dir, voicebox_profile_id="profile-1"),
        video_renderer=FakeRenderer(),  # type: ignore[arg-type]
    )

    def fake_narration(text: str, destination: Path) -> NarrationResult:
        received["voice_text"] = text
        destination.write_bytes(b"RIFF....WAVE")
        return NarrationResult(destination, "voicebox")

    monkeypatch.setattr(service, "_generate_narration", fake_narration)

    result = service.generate_video(
        _post(tmp_path),
        narration_script="くちを開いて話す",
        output_path=output,
    )

    assert result.video.output_path == output
    assert result.narration_provider == "voicebox"
    assert received["script"] == "ENFJと水瓶座の本当の恋愛傾向"
    assert received["voice_text"] == "くちを開いて話す。"
    assert received["destination"] == output
    assert received["subtitle_cards"] is None
    assert received["subtitle_durations"] is None
    assert not Path(received["narration"]).exists()


def test_generate_video_reports_voice_and_video_stages(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "web" / "src" / "data"
    data_dir.mkdir(parents=True)
    output = tmp_path / "finished.mp4"
    updates: list[tuple[int, str]] = []

    class FakeRenderer:
        def render(
            self,
            script,
            narration,
            destination,
            *,
            subtitle_cards=None,
            subtitle_durations=None,
            progress=None,
        ):
            assert progress is not None
            progress(75, "GPUで動画を書き出しています")
            Path(destination).write_bytes(b"video")
            return VideoRenderResult(Path(destination), 65.0, "h264_nvenc")

    service = MediaService(
        AppSettings(data_dir=data_dir, voicebox_profile_id="profile-1"),
        video_renderer=FakeRenderer(),  # type: ignore[arg-type]
    )

    def fake_narration(text, destination, *, progress=None):
        destination.write_bytes(b"RIFF....WAVE")
        return NarrationResult(destination, "voicebox")

    monkeypatch.setattr(service, "_generate_narration", fake_narration)

    result = service.generate_video(
        _post(tmp_path),
        output_path=output,
        progress=lambda percent, message: updates.append((percent, message)),
    )

    assert result.video.output_path == output
    assert [percent for percent, _message in updates] == [5, -1, 55, 75, 100]
    assert "Voicebox" in updates[1][1]
    assert "GPU" in updates[3][1]


def _write_pcm_wav(
    path: Path,
    *,
    frames: int,
    frame_rate: int = 8_000,
    channels: int = 1,
    sample_width: int = 2,
) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(frame_rate)
        writer.writeframes(b"\x00" * frames * channels * sample_width)


def test_voicevox_generates_each_subtitle_card_and_passes_real_durations(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "web" / "src" / "data"
    data_dir.mkdir(parents=True)
    output = tmp_path / "voicevox.mp4"
    calls: list[tuple[str, int, float]] = []
    received: dict[str, object] = {}
    updates: list[tuple[int, str]] = []

    class FakeVoicebox:
        def generate_wav(self, *args, **kwargs):
            raise AssertionError("VOICEVOX選択時はVoiceboxを呼ばない")

    class FakeVoicevox:
        def generate_wav(self, text, destination, *, speaker, speed_scale):
            calls.append((text, speaker, speed_scale))
            frame_count = 8_000 if len(calls) == 1 else 4_000
            _write_pcm_wav(Path(destination), frames=frame_count)
            return Path(destination)

    class FakeRenderer:
        def render(
            self,
            script,
            narration,
            destination,
            *,
            subtitle_cards=None,
            subtitle_durations=None,
            progress=None,
        ):
            with wave.open(str(narration), "rb") as reader:
                received["combined_frames"] = reader.getnframes()
            received["cards"] = subtitle_cards
            received["durations"] = subtitle_durations
            Path(destination).write_bytes(b"video")
            return VideoRenderResult(Path(destination), 1.5, "h264_nvenc")

    settings = AppSettings(
        data_dir=data_dir,
        voice_engine="voicevox",
        voicevox_speaker_id=8,
        voicevox_speed_scale=1.25,
        voicevox_fallback_enabled=False,
    )
    service = MediaService(
        settings,
        video_renderer=FakeRenderer(),  # type: ignore[arg-type]
        voicevox_cache_dir=tmp_path / "voicevox-cache",
    )
    service.voicebox = FakeVoicebox()  # type: ignore[assignment]
    service.voicevox = FakeVoicevox()  # type: ignore[assignment]
    post = replace(
        _post(tmp_path),
        tiktok_script=(
            "この境界の薄さは、\nあなた自身にとって\n最も厄介な、\n自分の特性です"
            "\n\n四つ目の字幕、\n最後の字幕"
        ),
    )

    result = service.generate_video(
        post,
        narration_script=(
            "このきょうかいの薄さは、\nあなた自身にとって\n最も厄介な、\n自分の特性です"
            "\n\nよっつめの字幕、\n最後の字幕"
        ),
        output_path=output,
        progress=lambda percent, message: updates.append((percent, message)),
    )

    assert result.narration_provider == "voicevox"
    assert [text for text, _speaker, _speed in calls] == [
        "このきょうかいの薄さは。",
        "あなた自身にとって最も厄介な。",
        "自分の特性です。",
        "よっつめの字幕。",
        "最後の字幕。",
    ]
    assert all("、" not in text for text, _speaker, _speed in calls)
    assert all((speaker, speed) == (8, 1.25) for _text, speaker, speed in calls)
    assert received["combined_frames"] == 24_000
    assert received["durations"] == (2.0, 1.0)
    assert len(received["cards"]) == 2  # type: ignore[arg-type]
    assert all(
        "、" not in line
        for card in received["cards"]  # type: ignore[union-attr]
        for line in card
    )
    assert any("（1/5）" in message for _percent, message in updates)
    assert any("（5/5）" in message for _percent, message in updates)


def test_voicevox_preview_uses_editable_reading_and_current_voice_settings(
    tmp_path: Path,
) -> None:
    output = tmp_path / "preview.wav"
    video_output = tmp_path / "preview-video.mp4"
    calls: list[tuple[str, int, float]] = []
    updates: list[tuple[int, str]] = []
    received: dict[str, object] = {}

    class FakeVoicevox:
        def generate_wav(self, text, destination, *, speaker, speed_scale):
            calls.append((text, speaker, speed_scale))
            _write_pcm_wav(Path(destination), frames=4_000)
            return Path(destination)

    class FakeRenderer:
        def render(
            self,
            script,
            narration,
            destination,
            *,
            subtitle_cards=None,
            subtitle_durations=None,
            progress=None,
        ):
            received["script"] = script
            received["narration"] = Path(narration)
            received["durations"] = subtitle_durations
            Path(destination).write_bytes(b"video")
            return VideoRenderResult(Path(destination), 1.0, "h264_nvenc")

    service = MediaService(
        AppSettings(
            voice_engine="voicevox",
            voicevox_speaker_id=46,
            voicevox_speed_scale=1.15,
        ),
        video_renderer=FakeRenderer(),  # type: ignore[arg-type]
        voicevox_cache_dir=tmp_path / "voicevox-cache",
    )
    service.voicevox = FakeVoicevox()  # type: ignore[assignment]
    post = replace(_post(tmp_path), tiktok_script="口を開く\n\n次の字幕")

    result = service.generate_voicevox_preview(
        post,
        narration_script="くちを開く\n\n次の字幕",
        output_path=output,
        progress=lambda percent, message: updates.append((percent, message)),
    )

    assert result.path == output
    assert result.subtitle_durations == (0.5, 0.5)
    assert [text for text, _speaker, _speed in calls] == [
        "くちを開く。",
        "次の字幕。",
    ]
    assert all(
        (speaker, speed) == (46, 1.15)
        for _text, speaker, speed in calls
    )
    assert output.is_file()
    assert updates[0] == (5, "確認用の音声を準備しています")
    assert updates[-1] == (100, "確認用のVOICEVOX音声ができました")

    class UnexpectedVoicevox:
        def generate_wav(self, *args, **kwargs):
            raise AssertionError("確認済み音声があるときはVOICEVOXを再実行しない")

    service.voicevox = UnexpectedVoicevox()  # type: ignore[assignment]
    video = service.generate_video(
        post,
        narration_script="くちを開く\n\n次の字幕",
        voice_preview=result,
        output_path=video_output,
    )

    assert video.narration_provider == "voicevox"
    assert received["script"] == "口を開く\n\n次の字幕"
    assert received["narration"] == output
    assert received["durations"] == (0.5, 0.5)


def test_generate_video_rejects_different_subtitle_and_voice_card_counts(
    tmp_path: Path,
) -> None:
    service = MediaService(AppSettings())
    post = replace(_post(tmp_path), tiktok_script="一枚目\n\n二枚目")

    with pytest.raises(VoiceServiceError, match="画面数が一致しません"):
        service.generate_video(
            post,
            narration_script="一枚目と二枚目",
            output_path=tmp_path / "invalid.mp4",
        )


def test_pcm_wav_concatenation_rejects_mixed_formats(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    destination = tmp_path / "combined.wav"
    _write_pcm_wav(first, frames=800, frame_rate=8_000)
    _write_pcm_wav(second, frames=1_600, frame_rate=16_000)

    with pytest.raises(VoiceServiceError, match="音声形式が一致しない"):
        _concatenate_pcm_wavs([first, second], destination)

    assert not destination.exists()


def test_pcm_wav_concatenation_rejects_empty_audio(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    destination = tmp_path / "combined.wav"
    _write_pcm_wav(empty, frames=0)

    with pytest.raises(VoiceServiceError, match="空の音声"):
        _concatenate_pcm_wavs([empty], destination)

    assert not destination.exists()
