from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QRadialGradient


VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
LOGO_RESERVED_HEIGHT = 360
SUBTITLE_CENTER_X = VIDEO_WIDTH // 2
SUBTITLE_CENTER_Y = VIDEO_HEIGHT // 2 - 60
SUBTITLE_FONT_FAMILY = "Zen Antique"
SUBTITLE_FONT_SIZE = 125
SUBTITLE_TEXT_COLOR = "#FEFFE2"
SUBTITLE_TEXT_COLOR_ASS = "&H00E2FFFE"
SUBTITLE_OUTLINE_THICKNESS = 14
SUBTITLE_SOFT_OUTLINE_BLUR = 8
SUBTITLE_FONT_PATH = (
    Path(__file__).resolve().parent
    / "assets"
    / "fonts"
    / "ZenAntique-Regular.ttf"
)
# 公開版の背景は create_starfield_background() で描いた自作PNGです。
BACKGROUND_VIDEO_PATH = Path(__file__).resolve().parent / "assets" / "images" / "starfield.png"
BGM_AUDIO_PATH = None  # 第三者の音源を配布しないため、公開版はナレーションのみ。
BGM_VOLUME = 0.12
VIDEO_LOGO_PATH = (
    Path(__file__).resolve().parent / "assets" / "images" / "stellalog_logo_touka.png"
)
BGM_FADE_IN_SECONDS = 1.0
BGM_FADE_OUT_SECONDS = 1.5


class VideoRenderError(RuntimeError):
    """利用者が画面上で読める動画生成エラー。"""


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_seconds: float
    end_seconds: float
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VideoRenderResult:
    output_path: Path
    duration_seconds: float
    video_encoder: str


def split_subtitle_cards(
    script: str,
    *,
    max_chars_per_line: int = 13,
    max_lines_per_card: int = 6,
    keep_voice_break_markers: bool = False,
) -> tuple[tuple[str, ...], ...]:
    """通常改行を同一カード、空白行をカード境界として字幕を分割する。

    読点はVOICEVOX用の非表示区切りとして扱うため、通常は字幕から除く。
    """
    if max_chars_per_line < 1:
        raise ValueError("字幕の1行の文字数は1以上で指定してください")
    if max_lines_per_card < 2:
        raise ValueError("字幕は1画面あたり2行以上に設定してください")

    normalised = script.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[list[str]] = []
    current_lines: list[str] = []
    for source_line in normalised.split("\n"):
        clean = " ".join(source_line.split()).strip()
        visible_text = clean.replace("、", "").strip()
        if not visible_text:
            if current_lines:
                paragraphs.append(current_lines)
                current_lines = []
            continue
        current_lines.extend(_wrap_subtitle_line(clean, max_chars_per_line))
    if current_lines:
        paragraphs.append(current_lines)

    if not paragraphs:
        raise VideoRenderError("動画に表示する台本が空です")

    cards: list[tuple[str, ...]] = []
    for paragraph in paragraphs:
        cards.extend(_split_lines_into_cards(paragraph, max_lines_per_card))
    if keep_voice_break_markers:
        return tuple(cards)
    return tuple(
        tuple(line.replace("、", "") for line in card)
        for card in cards
    )


def allocate_subtitle_cues(
    cards: Sequence[Sequence[str]], duration_seconds: float
) -> tuple[SubtitleCue, ...]:
    """字幕量に応じて、音声全体の長さを字幕カードへ配分する。"""
    if duration_seconds <= 0:
        raise VideoRenderError("ナレーション音声の長さを確認できませんでした")
    if not cards:
        raise VideoRenderError("動画に表示する字幕がありません")

    weights = [max(6, sum(len(line) for line in card)) for card in cards]
    total_weight = sum(weights)
    starts = [0.0]
    for weight in weights[:-1]:
        starts.append(starts[-1] + duration_seconds * weight / total_weight)
    ends = [*starts[1:], duration_seconds]
    return tuple(
        SubtitleCue(start, end, tuple(card))
        for start, end, card in zip(starts, ends, cards, strict=True)
    )


def allocate_subtitle_cues_from_durations(
    cards: Sequence[Sequence[str]], durations: Sequence[float]
) -> tuple[SubtitleCue, ...]:
    """カードごとの実音声長を累積し、正確な字幕時刻へ変換する。"""
    normalised_cards = _validate_subtitle_cards(cards)
    if isinstance(durations, (str, bytes)):
        raise VideoRenderError("字幕ごとの音声時間を正しく読み取れませんでした")
    duration_values = tuple(durations)
    if len(normalised_cards) != len(duration_values):
        raise VideoRenderError("字幕カードと音声時間の数が一致していません")

    parsed_durations: list[float] = []
    for duration in duration_values:
        if isinstance(duration, bool):
            raise VideoRenderError("字幕ごとの音声時間は0秒より長くしてください")
        try:
            value = float(duration)
        except (TypeError, ValueError) as exc:
            raise VideoRenderError("字幕ごとの音声時間を正しく読み取れませんでした") from exc
        if not math.isfinite(value) or value <= 0:
            raise VideoRenderError("字幕ごとの音声時間は0秒より長くしてください")
        parsed_durations.append(value)

    cues: list[SubtitleCue] = []
    elapsed = 0.0
    for card, duration in zip(normalised_cards, parsed_durations, strict=True):
        end = elapsed + duration
        cues.append(SubtitleCue(elapsed, end, card))
        elapsed = end
    return tuple(cues)


def escape_ass_text(text: str) -> str:
    """台本文字をASS字幕の命令として解釈されないようにする。"""
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\r", r"\N")
        .replace("\n", r"\N")
    )


def build_ass_document(cues: Sequence[SubtitleCue]) -> str:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SoftOutline,{SUBTITLE_FONT_FAMILY},{SUBTITLE_FONT_SIZE},&HFFE2FFFE,&HFFE2FFFE,&H00000000,&HFF000000,0,0,0,0,100,100,1,0,1,{SUBTITLE_OUTLINE_THICKNESS},0,5,70,70,80,1
Style: Default,{SUBTITLE_FONT_FAMILY},{SUBTITLE_FONT_SIZE},{SUBTITLE_TEXT_COLOR_ASS},{SUBTITLE_TEXT_COLOR_ASS},&H00000000,&HFF000000,0,0,0,0,100,100,1,0,1,{SUBTITLE_OUTLINE_THICKNESS},0,5,70,70,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue = []
    for cue in cues:
        text = r"\N".join(escape_ass_text(line) for line in cue.lines)
        dialogue.append(
            "Dialogue: 0,"
            f"{_ass_timestamp(cue.start_seconds)},{_ass_timestamp(cue.end_seconds)},"
            "SoftOutline,,0,0,0,,"
            f"{{\\pos({SUBTITLE_CENTER_X},{SUBTITLE_CENTER_Y})"
            f"\\blur{SUBTITLE_SOFT_OUTLINE_BLUR}}}{text}"
        )
        dialogue.append(
            "Dialogue: 1,"
            f"{_ass_timestamp(cue.start_seconds)},{_ass_timestamp(cue.end_seconds)},"
            f"Default,,0,0,0,,{{\\pos({SUBTITLE_CENTER_X},{SUBTITLE_CENTER_Y})}}{text}"
        )
    return header + "\n".join(dialogue) + "\n"


def build_ffmpeg_command(
    *,
    ffmpeg_executable: str,
    background_path: Path,
    narration_path: Path,
    bgm_path: Path | None,
    output_path: Path,
    duration_seconds: float,
    encoder: str,
    logo_path: Path = VIDEO_LOGO_PATH,
) -> list[str]:
    """shellを介さず実行できるFFmpegの引数配列を返す。"""
    logo_index = 3 if bgm_path is not None else 2
    filter_graph = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,fps=30,format=yuv420p[background];"
        f"[{logo_index}:v]scale=400:-1,format=rgba[logo];"
        "[background][logo]overlay=x=(W-w)/2:y=H-h-40,"
        "ass=captions.ass:fontsdir=fonts,format=yuv420p[v];"
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:"
        "channel_layouts=stereo"
    )
    if bgm_path is None:
        filter_graph += ",alimiter=limit=0.95[a]"
    else:
        fade_out_duration = min(BGM_FADE_OUT_SECONDS, duration_seconds)
        fade_out_start = max(0.0, duration_seconds - fade_out_duration)
        filter_graph += (
            "[narration];[2:a]aresample=48000,aformat=sample_fmts=fltp:"
            f"channel_layouts=stereo,volume={BGM_VOLUME},"
            f"afade=t=in:st=0:d={BGM_FADE_IN_SECONDS},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_duration:.3f}[bgm];"
            "[narration][bgm]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0,alimiter=limit=0.95[a]"
        )
    command = [ffmpeg_executable, "-y", "-hide_banner", "-loglevel", "error"]
    if background_path.suffix.lower() == ".png":
        command.extend(("-loop", "1", "-framerate", str(VIDEO_FPS)))
    else:
        command.extend(("-stream_loop", "-1"))
    command.extend(("-i", str(background_path), "-i", str(narration_path)))
    if bgm_path is not None:
        command.extend(("-stream_loop", "-1", "-i", str(bgm_path)))
    command.extend((
        "-i", str(logo_path), "-filter_complex", filter_graph,
        "-map", "[v]", "-map", "[a]", "-c:v", encoder,
    ))
    if encoder == "h264_nvenc":
        command.extend(("-preset", "p4", "-cq", "21"))
    else:
        command.extend(("-preset", "medium", "-crf", "20"))
    command.extend(
        (
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-r",
            str(VIDEO_FPS),
            "-t",
            f"{duration_seconds:.3f}",
            "-shortest",
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        )
    )
    return command


class VideoRenderer:
    def __init__(
        self,
        *,
        ffmpeg_executable: str = "ffmpeg",
        ffprobe_executable: str = "ffprobe",
        subtitle_font_path: Path | str = SUBTITLE_FONT_PATH,
        background_video_path: Path | str = BACKGROUND_VIDEO_PATH,
        bgm_audio_path: Path | str | None = BGM_AUDIO_PATH,
        logo_path: Path | str = VIDEO_LOGO_PATH,
    ) -> None:
        self.ffmpeg_executable = ffmpeg_executable
        self.ffprobe_executable = ffprobe_executable
        self.subtitle_font_path = Path(subtitle_font_path).resolve()
        self.background_video_path = Path(background_video_path).resolve()
        self.bgm_audio_path = Path(bgm_audio_path).resolve() if bgm_audio_path is not None else None
        self.logo_path = Path(logo_path).resolve()

    def render(
        self,
        script: str,
        narration_wav: Path | str,
        output_mp4: Path | str,
        *,
        progress: Callable[[int, str], None] | None = None,
        subtitle_cards: Sequence[Sequence[str]] | None = None,
        subtitle_durations: Sequence[float] | None = None,
    ) -> VideoRenderResult:
        if (subtitle_cards is None) != (subtitle_durations is None):
            raise VideoRenderError(
                "字幕カードと字幕ごとの音声時間は、両方を一緒に指定してください"
            )
        narration_path = Path(narration_wav).resolve()
        output_path = Path(output_mp4).resolve()
        self._validate_inputs(
            narration_path,
            self.background_video_path,
            self.bgm_audio_path,
            output_path,
            self.subtitle_font_path,
        )
        duration = self._probe_duration(narration_path)
        if not self.logo_path.is_file():
            raise VideoRenderError(
                "動画用のロゴが見つかりません。アプリをもう一度セットアップしてください。"
            )
        _report(progress, 60, "字幕を読みやすい長さに分割しています")
        if subtitle_cards is not None and subtitle_durations is not None:
            cues = allocate_subtitle_cues_from_durations(
                subtitle_cards, subtitle_durations
            )
        else:
            cards = split_subtitle_cards(script)
            cues = allocate_subtitle_cues(cards, duration)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="stellalog-video-") as temp_name:
            temp_dir = Path(temp_name)
            captions_path = temp_dir / "captions.ass"
            fonts_dir = temp_dir / "fonts"
            temporary_output = temp_dir / "rendered.mp4"
            _report(progress, 65, "自作の星空背景と字幕を準備しています")
            captions_path.write_text(build_ass_document(cues), encoding="utf-8-sig")
            fonts_dir.mkdir()
            shutil.copy2(
                self.subtitle_font_path,
                fonts_dir / self.subtitle_font_path.name,
            )

            first_error = ""
            selected_encoder = "h264_nvenc"
            for encoder in ("h264_nvenc", "libx264"):
                if temporary_output.exists():
                    temporary_output.unlink()
                command = build_ffmpeg_command(
                    ffmpeg_executable=self.ffmpeg_executable,
                    background_path=self.background_video_path,
                    narration_path=narration_path,
                    bgm_path=self.bgm_audio_path,
                    output_path=temporary_output,
                    duration_seconds=duration,
                    encoder=encoder,
                    logo_path=self.logo_path,
                )
                if encoder == "h264_nvenc":
                    _report(progress, 75, "NVIDIA GPUで動画を書き出しています")
                else:
                    _report(
                        progress,
                        75,
                        "GPU方式を使えなかったため、互換方式で動画を書き出しています",
                    )
                try:
                    completed = subprocess.run(
                        command,
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        creationflags=_no_window_flag(),
                    )
                except FileNotFoundError as exc:
                    raise VideoRenderError(
                        "動画生成に必要なFFmpegが見つかりません。FFmpegをインストールしてから、もう一度お試しください。"
                    ) from exc
                if completed.returncode == 0 and temporary_output.is_file():
                    selected_encoder = encoder
                    break
                if encoder == "h264_nvenc":
                    first_error = completed.stderr
                    continue
                details = (completed.stderr or first_error).strip()[-800:]
                raise VideoRenderError(
                    "動画を書き出せませんでした。ナレーションと背景を確認して、もう一度お試しください。"
                    + (f"\nFFmpegからの情報: {details}" if details else "")
                )
            else:  # pragma: no cover - 直前の分岐で必ず終了する
                raise VideoRenderError("動画を書き出せませんでした")

            if not temporary_output.is_file() or temporary_output.stat().st_size == 0:
                raise VideoRenderError("動画の書き出し結果が空でした。もう一度お試しください。")
            os.replace(temporary_output, output_path)
            _report(progress, 95, "完成動画を保存しています")

        return VideoRenderResult(output_path, duration, selected_encoder)

    def _probe_duration(self, narration_path: Path) -> float:
        command = [
            self.ffprobe_executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(narration_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                creationflags=_no_window_flag(),
            )
        except FileNotFoundError as exc:
            raise VideoRenderError(
                "音声確認に必要なFFprobeが見つかりません。FFmpegをインストールしてから、もう一度お試しください。"
            ) from exc
        if completed.returncode != 0:
            raise VideoRenderError(
                "ナレーション音声を読み込めませんでした。WAVファイルを選び直してください。"
            )
        try:
            duration = float(json.loads(completed.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VideoRenderError(
                "ナレーション音声の長さを確認できませんでした。WAVファイルを選び直してください。"
            ) from exc
        if not math.isfinite(duration) or duration <= 0:
            raise VideoRenderError("ナレーション音声の中身が空です")
        return duration

    @staticmethod
    def _validate_inputs(
        narration_path: Path,
        background_video_path: Path,
        bgm_audio_path: Path | None,
        output_path: Path,
        subtitle_font_path: Path,
    ) -> None:
        if not narration_path.is_file():
            raise VideoRenderError("ナレーション音声が見つかりません。WAVファイルを選んでください。")
        if narration_path.suffix.lower() != ".wav":
            raise VideoRenderError("ナレーション音声はWAV形式のファイルを選んでください。")
        if not background_video_path.is_file():
            raise VideoRenderError(
                "動画用の星空背景が見つかりません。アプリをもう一度セットアップしてください。"
            )
        if background_video_path.suffix.lower() not in {".png", ".mp4"}:
            raise VideoRenderError("動画用の背景はPNGまたはMP4形式を使用してください。")
        if bgm_audio_path is not None and not bgm_audio_path.is_file():
            raise VideoRenderError(
                "動画用のBGMが見つかりません。アプリをもう一度セットアップしてください。"
            )
        if bgm_audio_path is not None and bgm_audio_path.suffix.lower() != ".mp3":
            raise VideoRenderError("動画用のBGMはMP3形式を使用してください。")
        if output_path.suffix.lower() != ".mp4":
            raise VideoRenderError("動画の保存先は.mp4で終わるファイル名にしてください。")
        if not subtitle_font_path.is_file():
            raise VideoRenderError(
                "動画字幕用のZen Antique Regularフォントが見つかりません。"
                "アプリをもう一度セットアップしてください。"
            )
        if subtitle_font_path.suffix.lower() not in {".ttf", ".otf"}:
            raise VideoRenderError("動画字幕用フォントの形式を確認できませんでした。")


def create_starfield_background(output_path: Path | str) -> None:
    """外部素材を使わず、紫色の星空と星座線をPNGへ描画する。"""
    path = Path(output_path)
    image = QImage(VIDEO_WIDTH, VIDEO_HEIGHT, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    sky = QLinearGradient(0, 0, VIDEO_WIDTH, VIDEO_HEIGHT)
    sky.setColorAt(0.0, QColor("#120720"))
    sky.setColorAt(0.48, QColor("#32104d"))
    sky.setColorAt(1.0, QColor("#090311"))
    painter.fillRect(image.rect(), sky)

    glow = QRadialGradient(QPointF(760, 620), 650)
    glow.setColorAt(0.0, QColor(151, 78, 210, 105))
    glow.setColorAt(0.5, QColor(92, 38, 150, 42))
    glow.setColorAt(1.0, QColor(30, 8, 58, 0))
    painter.fillRect(image.rect(), glow)

    rng = random.Random(813_2026)
    painter.setPen(Qt.PenStyle.NoPen)
    for _ in range(520):
        x = rng.randrange(VIDEO_WIDTH)
        y = rng.randrange(VIDEO_HEIGHT)
        radius = rng.choice((1, 1, 1, 2, 2, 3))
        alpha = rng.randrange(100, 235)
        painter.setBrush(QColor(244, 229, 255, alpha))
        painter.drawEllipse(QPointF(x, y), radius, radius)

    constellations = (
        ((95, 370), (270, 290), (380, 440), (520, 355), (610, 510)),
        ((650, 1050), (785, 920), (930, 1040), (835, 1205), (1000, 1340)),
        ((90, 1470), (230, 1370), (350, 1540), (480, 1440)),
    )
    painter.setPen(QPen(QColor(205, 164, 255, 75), 2))
    for points in constellations:
        for first, second in zip(points, points[1:]):
            painter.drawLine(QPointF(*first), QPointF(*second))
        for x, y in points:
            painter.setBrush(QColor(255, 244, 255, 215))
            painter.setPen(QPen(QColor(218, 178, 255, 130), 2))
            painter.drawEllipse(QPointF(x, y), 5, 5)
    painter.end()

    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path), "PNG"):
        raise VideoRenderError("動画用の星空背景を作成できませんでした")


def _wrap_subtitle_line(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        split_at = _preferred_japanese_break(remaining, max_chars)
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return [part for part in parts if part]


def _preferred_japanese_break(text: str, max_chars: int) -> int:
    """句読点や助詞の後を優先し、不自然な語中切断をできるだけ避ける。"""
    window = text[:max_chars]
    minimum = max(1, max_chars // 2)
    candidates: list[tuple[int, int]] = []

    # 数字が小さいほど、文章として強い区切りとして優先する。
    boundaries = (
        (0, "、。！？!?　 "),
        (1, ("という", "として", "けれど", "だけど", "だから", "なので")),
        (2, ("から", "まで", "より", "では", "には", "とは", "ても", "でも", "ので", "のに")),
        (3, ("は", "が", "を", "に", "で", "と", "へ", "も")),
    )
    punctuation = boundaries[0][1]
    assert isinstance(punctuation, str)
    for mark in punctuation:
        position = window.rfind(mark) + 1
        if position >= minimum:
            candidates.append((0, position))
    for priority, endings in boundaries[1:]:
        assert not isinstance(endings, str)
        for ending in endings:
            search_from = 0
            while True:
                index = window.find(ending, search_from)
                if index < 0:
                    break
                position = index + len(ending)
                if position >= minimum:
                    candidates.append((priority, position))
                search_from = index + 1

    if not candidates:
        return max_chars
    best_priority = min(priority for priority, _ in candidates)
    return max(position for priority, position in candidates if priority == best_priority)


def _split_lines_into_cards(
    lines: Sequence[str], max_lines_per_card: int
) -> list[tuple[str, ...]]:
    if len(lines) <= max_lines_per_card:
        return [tuple(lines)]
    # 最後だけ1行になるのを避けながら、元の行順と空白行の境界を守る。
    card_count = math.ceil(len(lines) / max_lines_per_card)
    base_size, extra = divmod(len(lines), card_count)
    sizes = [base_size + (1 if index < extra else 0) for index in range(card_count)]
    result: list[tuple[str, ...]] = []
    offset = 0
    for size in sizes:
        result.append(tuple(lines[offset : offset + size]))
        offset += size
    return result


def _validate_subtitle_cards(
    cards: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    if isinstance(cards, (str, bytes)):
        raise VideoRenderError("字幕カードを正しく読み取れませんでした")
    normalised: list[tuple[str, ...]] = []
    for card in cards:
        if isinstance(card, (str, bytes)):
            raise VideoRenderError("字幕カードは行ごとの文字列で指定してください")
        lines = tuple(str(line).strip() for line in card)
        if not lines or any(not line for line in lines):
            raise VideoRenderError("空の字幕カードまたは字幕行は使用できません")
        if len(lines) > 6:
            raise VideoRenderError("字幕カードは1画面6行以内にしてください")
        normalised.append(lines)
    if not normalised:
        raise VideoRenderError("動画に表示する字幕がありません")
    return tuple(normalised)


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}"


def _no_window_flag() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _report(
    progress: Callable[[int, str], None] | None,
    percent: int,
    message: str,
) -> None:
    if progress is not None:
        progress(percent, message)
