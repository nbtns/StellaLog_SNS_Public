from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest
from stellalog_sns.video_renderer import (
    BACKGROUND_VIDEO_PATH,
    BGM_AUDIO_PATH,
    BGM_FADE_IN_SECONDS,
    BGM_FADE_OUT_SECONDS,
    BGM_VOLUME,
    LOGO_RESERVED_HEIGHT,
    SUBTITLE_FONT_FAMILY,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_FONT_PATH,
    SUBTITLE_OUTLINE_THICKNESS,
    SUBTITLE_SOFT_OUTLINE_BLUR,
    SUBTITLE_CENTER_X,
    SUBTITLE_CENTER_Y,
    SUBTITLE_TEXT_COLOR,
    SUBTITLE_TEXT_COLOR_ASS,
    VIDEO_FPS,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    VIDEO_LOGO_PATH,
    VideoRenderer,
    allocate_subtitle_cues,
    allocate_subtitle_cues_from_durations,
    build_ass_document,
    build_ffmpeg_command,
    escape_ass_text,
    split_subtitle_cards,
)


def test_split_subtitle_cards_keeps_two_to_six_readable_lines() -> None:
    script = "\n".join(
        (
            "ENFJ×水瓶座の本当の恋愛傾向",
            "相手の気持ちを先回りして考えます",
            "気づかないうちに無理を重ねることがあります",
            "自分の希望も短い言葉で伝えてみましょう",
            "当てはまるところはありますか？",
            "詳しい続きはStellaLogの記事でどうぞ",
        )
    )

    cards = split_subtitle_cards(script, max_chars_per_line=14)

    assert len(cards) >= 2
    assert all(2 <= len(card) <= 6 for card in cards)
    assert all(len(line) <= 14 for card in cards for line in card)
    assert "".join(line for card in cards for line in card).replace(" ", "") == script.replace(
        "\n", ""
    ).replace(" ", "")


def test_normal_newlines_stay_on_same_card_and_blank_lines_start_next_card() -> None:
    cards = split_subtitle_cards(
        "最初の1行\n最初の2行\n\n次の1行\n次の2行",
        max_chars_per_line=20,
    )

    assert cards == (("最初の1行", "最初の2行"), ("次の1行", "次の2行"))


def test_voice_break_commas_are_hidden_from_subtitle_cards() -> None:
    script = "少し考えて、\n言葉を選びます\n\nでも、気持ちは同じです"

    cards = split_subtitle_cards(script, max_chars_per_line=20)
    narration_cards = split_subtitle_cards(
        script,
        max_chars_per_line=20,
        keep_voice_break_markers=True,
    )

    assert cards == (
        ("少し考えて", "言葉を選びます"),
        ("でも気持ちは同じです",),
    )
    assert narration_cards == (
        ("少し考えて、", "言葉を選びます"),
        ("でも、気持ちは同じです",),
    )


def test_user_edited_five_line_card_is_preserved_exactly() -> None:
    lines = (
        "考えすぎても",
        "自分を責めないで",
        "慎重に選ぶのは",
        "大切にしたいものが",
        "あるからです",
    )

    assert all(len(line) <= 13 for line in lines)
    assert split_subtitle_cards("\n".join(lines)) == (lines,)


def test_user_edited_six_line_card_is_preserved_exactly() -> None:
    lines = (
        "ありとあらゆる",
        "感覚情報を",
        "快か不快に",
        "仕分ける装置が",
        "ノンストップで",
        "稼働しています",
    )

    assert split_subtitle_cards("\n".join(lines)) == (lines,)


def test_only_long_lines_wrap_and_more_than_six_lines_split_safely() -> None:
    cards = split_subtitle_cards(
        "短い\nこれは十文字を超える長い字幕行です\n三行目\n四行目\n五行目\n六行目",
        max_chars_per_line=10,
    )

    assert len(cards) == 2
    assert all(2 <= len(card) <= 6 for card in cards)
    assert cards[0][0] == "短い"
    assert "".join(line for card in cards for line in card) == (
        "短いこれは十文字を超える長い字幕行です三行目四行目五行目六行目"
    )


def test_long_japanese_line_prefers_particle_boundary_over_word_cut() -> None:
    cards = split_subtitle_cards(
        "相手の気持ちを先回りして考えます",
        max_chars_per_line=13,
    )

    assert cards == (("相手の気持ちを", "先回りして考えます"),)


def test_cues_follow_real_audio_duration_and_text_weight() -> None:
    cards = (("短い字幕", "です"), ("こちらは文字数が多い字幕です", "続きです"))
    cues = allocate_subtitle_cues(cards, 12.5)

    assert cues[0].start_seconds == 0
    assert cues[-1].end_seconds == 12.5
    assert cues[0].end_seconds == cues[1].start_seconds
    assert (cues[1].end_seconds - cues[1].start_seconds) > (
        cues[0].end_seconds - cues[0].start_seconds
    )


def test_card_audio_durations_create_exact_cumulative_cues() -> None:
    cues = allocate_subtitle_cues_from_durations(
        (("1枚目", "続き"), ("2枚目",), ("3枚目", "終わり")),
        (1.25, 2.5, 0.75),
    )

    assert [(cue.start_seconds, cue.end_seconds) for cue in cues] == [
        (0.0, 1.25),
        (1.25, 3.75),
        (3.75, 4.5),
    ]


@pytest.mark.parametrize(
    ("cards", "durations", "message"),
    (
        ((("1枚目",), ("2枚目",)), (1.0,), "数が一致"),
        ((("1枚目",),), (0.0,), "0秒より長く"),
        ((("1枚目",),), (-1.0,), "0秒より長く"),
    ),
)
def test_card_audio_duration_validation_is_clear(
    cards: tuple[tuple[str, ...], ...],
    durations: tuple[float, ...],
    message: str,
) -> None:
    with pytest.raises(Exception, match=message):
        allocate_subtitle_cues_from_durations(cards, durations)


def test_render_requires_cards_and_durations_together(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="両方を一緒に指定"):
        VideoRenderer().render(
            "台本",
            tmp_path / "missing.wav",
            tmp_path / "result.mp4",
            subtitle_cards=(("字幕",),),
        )


def test_ass_text_escapes_commands_and_newlines() -> None:
    assert escape_ass_text("A{\\pos(1,2)}\nB") == r"A\{\\pos(1,2)\}\NB"
    document = build_ass_document(
        allocate_subtitle_cues((("1行目", "2行目"),), 3.0)
    )
    assert "PlayResX: 1080" in document
    assert "PlayResY: 1920" in document
    assert f"Style: SoftOutline,{SUBTITLE_FONT_FAMILY},{SUBTITLE_FONT_SIZE}" in document
    assert f"Style: Default,{SUBTITLE_FONT_FAMILY},{SUBTITLE_FONT_SIZE}" in document
    assert SUBTITLE_TEXT_COLOR == "#FEFFE2"
    assert document.count(SUBTITLE_TEXT_COLOR_ASS) == 2
    assert document.count(
        f",0,0,0,0,100,100,1,0,1,{SUBTITLE_OUTLINE_THICKNESS},0,5,70,70,80,1"
    ) == 2
    assert f"\\blur{SUBTITLE_SOFT_OUTLINE_BLUR}" in document
    assert document.count(f"\\pos({SUBTITLE_CENTER_X},{SUBTITLE_CENTER_Y})") == 2
    assert r"1行目\N2行目" in document
    assert "Dialogue: 0,0:00:00.00,0:00:03.00,SoftOutline" in document
    assert "Dialogue: 1,0:00:00.00,0:00:03.00,Default" in document


def test_ffmpeg_command_is_an_argument_array_and_uses_requested_encoder(tmp_path: Path) -> None:
    command = build_ffmpeg_command(
        ffmpeg_executable="ffmpeg",
        background_path=tmp_path / "background video.mp4",
        narration_path=tmp_path / "voice;name.wav",
        bgm_path=tmp_path / "background music.mp3",
        output_path=tmp_path / "result.mp4",
        duration_seconds=61.25,
        encoder="h264_nvenc",
    )

    assert isinstance(command, list)
    assert command[0] == "ffmpeg"
    assert command.count("-stream_loop") == 2
    assert all(command[index + 1] == "-1" for index, value in enumerate(command) if value == "-stream_loop")
    assert str(tmp_path / "background video.mp4") in command
    assert str(tmp_path / "voice;name.wav") in command
    assert str(tmp_path / "background music.mp3") in command
    assert str(VIDEO_LOGO_PATH) in command
    assert command[command.index("-c:v") + 1] == "h264_nvenc"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-t") + 1] == "61.250"
    assert "scale=1080:1920" in command[command.index("-filter_complex") + 1]
    assert "crop=1080:1920" in command[command.index("-filter_complex") + 1]
    assert "ass=captions.ass:fontsdir=fonts" in command[command.index("-filter_complex") + 1]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "delogo=" not in filter_graph
    assert "[3:v]scale=400:-1,format=rgba[logo]" in filter_graph
    assert "[background][logo]overlay=x=(W-w)/2:y=H-h-40" in filter_graph
    assert filter_graph.count("channel_layouts=stereo") == 2
    assert f"volume={BGM_VOLUME}" in filter_graph
    assert f"afade=t=in:st=0:d={BGM_FADE_IN_SECONDS}" in filter_graph
    assert f"d={BGM_FADE_OUT_SECONDS:.3f}[bgm]" in filter_graph
    assert "amix=inputs=2:duration=first" in filter_graph
    assert "alimiter=limit=0.95[a]" in filter_graph
    assert "[a]" in command


def test_bundled_background_video_and_zen_antique_font_exist() -> None:
    from PySide6.QtGui import QImage

    logo = QImage(str(VIDEO_LOGO_PATH))
    assert not logo.isNull()
    assert logo.hasAlphaChannel()
    assert logo.pixelColor(0, 0).alpha() == 0
    assert BACKGROUND_VIDEO_PATH.is_file()
    assert BACKGROUND_VIDEO_PATH.name == "starfield.png"
    assert BGM_AUDIO_PATH is None
    assert SUBTITLE_FONT_PATH.is_file()
    assert SUBTITLE_FONT_PATH.name == "ZenAntique-Regular.ttf"
    assert SUBTITLE_FONT_SIZE == 125
    assert SUBTITLE_OUTLINE_THICKNESS == 14
    assert SUBTITLE_SOFT_OUTLINE_BLUR == 8
    assert LOGO_RESERVED_HEIGHT == 360
    assert (SUBTITLE_CENTER_X, SUBTITLE_CENTER_Y) == (540, 900)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg/FFprobeがない環境では実動画テストを省略",
)
def test_renders_short_vertical_h264_video_with_aac_audio(tmp_path: Path) -> None:
    narration = tmp_path / "voice.wav"
    output = tmp_path / "result.mp4"
    _make_silent_wav(narration, seconds=1.2)

    result = VideoRenderer().render(
        "ENFJ×水瓶座\n本当の恋愛傾向\n自分の気持ちも\n大切にしましょう",
        narration,
        output,
    )

    assert result.output_path == output.resolve()
    assert result.video_encoder in {"h264_nvenc", "libx264"}
    assert output.is_file() and output.stat().st_size > 0
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    video = next(stream for stream in streams if "width" in stream)
    audio = next(stream for stream in streams if stream["codec_name"] == "aac")
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (VIDEO_WIDTH, VIDEO_HEIGHT)
    assert video["r_frame_rate"] == f"{VIDEO_FPS}/1"
    assert audio["codec_name"] == "aac"


def _make_silent_wav(path: Path, *, seconds: float) -> None:
    sample_rate = 16_000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\0\0" * int(sample_rate * seconds))
