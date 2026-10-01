from __future__ import annotations

from datetime import datetime
from pathlib import Path
import wave

import pytest

from stellalog_sns.media_service import (
    GeneratedVoiceCardPreview,
    MediaService,
    _is_valid_pcm_wav,
)
from stellalog_sns.models import AppSettings, Article, PostSet
from stellalog_sns.voice_services import VoiceServiceError


def _post(tmp_path: Path, script: str) -> PostSet:
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
        selected_at=datetime(2026, 9, 5, 12, 0),
        tiktok_script=script,
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


def _write_pcm_wav(path: Path, *, frames: int = 800) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8_000)
        writer.writeframes(b"\x00" * frames * 2)


class _FakeVoicevox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    def generate_wav(self, text, destination, *, speaker, speed_scale):
        self.calls.append((text, speaker, speed_scale))
        _write_pcm_wav(Path(destination))
        return Path(destination)


def _service(tmp_path: Path, *, speed_scale: float = 1.0) -> tuple[MediaService, _FakeVoicevox]:
    service = MediaService(
        AppSettings(
            voice_engine="voicevox",
            voicevox_url="http://127.0.0.1:50021",
            voicevox_speaker_id=46,
            voicevox_speed_scale=speed_scale,
        ),
        voicevox_cache_dir=tmp_path / "voicevox-cache",
    )
    fake = _FakeVoicevox()
    service.voicevox = fake  # type: ignore[assignment]
    return service, fake


def test_voicevox_cache_regenerates_only_changed_segment(tmp_path: Path) -> None:
    service, voicevox = _service(tmp_path)
    post = _post(tmp_path, "一枚目\n\n二枚目")

    service.generate_voicevox_preview(
        post,
        narration_script="いち、共通\n\nに",
        output_path=tmp_path / "first.wav",
    )
    service.generate_voicevox_preview(
        post,
        narration_script="いち、変更\n\nに",
        output_path=tmp_path / "second.wav",
    )

    assert [text for text, _speaker, _speed in voicevox.calls] == [
        "いち。",
        "共通。",
        "に。",
        "変更。",
    ]
    assert len(list((tmp_path / "voicevox-cache").rglob("*.wav"))) == 4


def test_voicevox_cache_uses_new_entry_when_speed_changes(tmp_path: Path) -> None:
    post = _post(tmp_path, "一枚目")
    normal_service, normal_voicevox = _service(tmp_path, speed_scale=1.0)
    fast_service, fast_voicevox = _service(tmp_path, speed_scale=1.25)

    normal_service.generate_voicevox_preview(
        post,
        narration_script="同じ読み",
        output_path=tmp_path / "normal.wav",
    )
    fast_service.generate_voicevox_preview(
        post,
        narration_script="同じ読み",
        output_path=tmp_path / "fast.wav",
    )

    assert normal_voicevox.calls == [("同じ読み。", 46, 1.0)]
    assert fast_voicevox.calls == [("同じ読み。", 46, 1.25)]
    assert len(list((tmp_path / "voicevox-cache").rglob("*.wav"))) == 2


def test_voicevox_cache_replaces_corrupt_wav_after_regeneration(tmp_path: Path) -> None:
    service, voicevox = _service(tmp_path)
    post = _post(tmp_path, "一枚目")

    service.generate_voicevox_preview(
        post,
        narration_script="壊れた場合",
        output_path=tmp_path / "first.wav",
    )
    cache_path = next((tmp_path / "voicevox-cache").rglob("*.wav"))
    cache_path.write_bytes(b"corrupt")

    service.generate_voicevox_preview(
        post,
        narration_script="壊れた場合",
        output_path=tmp_path / "second.wav",
    )

    assert len(voicevox.calls) == 2
    assert _is_valid_pcm_wav(cache_path)


def test_voicevox_cache_keeps_old_file_when_regeneration_fails(tmp_path: Path) -> None:
    service, _voicevox = _service(tmp_path)
    post = _post(tmp_path, "一枚目")
    service.generate_voicevox_preview(
        post,
        narration_script="再生成に失敗",
        output_path=tmp_path / "first.wav",
    )
    cache_path = next((tmp_path / "voicevox-cache").rglob("*.wav"))
    cache_path.write_bytes(b"corrupt-but-preserved")

    class FailingVoicevox:
        def generate_wav(self, *args, **kwargs):
            raise VoiceServiceError("VOICEVOXを利用できません")

    service.voicevox = FailingVoicevox()  # type: ignore[assignment]
    with pytest.raises(VoiceServiceError, match="VOICEVOXを利用できません"):
        service.generate_voicevox_preview(
            post,
            narration_script="再生成に失敗",
            output_path=tmp_path / "second.wav",
        )

    assert cache_path.read_bytes() == b"corrupt-but-preserved"


def test_voicevox_card_preview_generates_only_selected_card(tmp_path: Path) -> None:
    service, voicevox = _service(tmp_path)
    post = _post(tmp_path, "一枚目\n\n二枚目\n\n三枚目")
    updates: list[tuple[int, str]] = []

    result = service.generate_voicevox_card_preview(
        post,
        1,
        narration_script="ひとつ\n\nふたつ、後半\n\nみっつ",
        output_path=tmp_path / "card.wav",
        progress=lambda percent, message: updates.append((percent, message)),
    )

    assert isinstance(result, GeneratedVoiceCardPreview)
    assert result.path == tmp_path / "card.wav"
    assert result.duration == pytest.approx(0.2)
    assert result.card_index == 1
    assert [text for text, _speaker, _speed in voicevox.calls] == [
        "ふたつ。",
        "後半。",
    ]
    assert updates[0] == (5, "選んだ字幕の音声を準備しています")
    assert updates[-1] == (100, "選んだ字幕のVOICEVOX音声ができました")


def test_voicevox_card_preview_rejects_missing_card(tmp_path: Path) -> None:
    service, _voicevox = _service(tmp_path)
    post = _post(tmp_path, "一枚目")

    with pytest.raises(VoiceServiceError, match="字幕が見つかりません"):
        service.generate_voicevox_card_preview(post, 1)


def test_long_narration_reading_keeps_blank_line_card_index(tmp_path: Path) -> None:
    service, voicevox = _service(tmp_path)
    post = _post(
        tmp_path,
        "一行目\n二行目\n三行目\n四行目\n五行目\n六行目\n\n二枚目",
    )
    long_reading = "ながいひらがなのよみ" * 12
    narration_script = f"{long_reading}\n\nにまいめ"

    card_result = service.generate_voicevox_card_preview(
        post,
        1,
        narration_script=narration_script,
        output_path=tmp_path / "card.wav",
    )
    full_result = service.generate_voicevox_preview(
        post,
        narration_script=narration_script,
        output_path=tmp_path / "full.wav",
    )

    assert card_result.card_index == 1
    assert len(full_result.subtitle_durations) == 2
    assert [text for text, _speaker, _speed in voicevox.calls] == [
        "にまいめ。",
        f"{long_reading}。",
    ]


def test_voicevox_preview_rejects_subtitle_block_over_six_lines(tmp_path: Path) -> None:
    service, voicevox = _service(tmp_path)
    seven_lines = "\n".join(f"{index}行目" for index in range(1, 8))
    post = _post(tmp_path, seven_lines)

    with pytest.raises(VoiceServiceError, match="同じ位置に空白行.*1画面を6行以内"):
        service.generate_voicevox_preview(
            post,
            narration_script=seven_lines,
            output_path=tmp_path / "full.wav",
        )
    with pytest.raises(VoiceServiceError, match="同じ位置に空白行.*1画面を6行以内"):
        service.generate_voicevox_card_preview(
            post,
            0,
            narration_script=seven_lines,
            output_path=tmp_path / "card.wav",
        )

    assert voicevox.calls == []
