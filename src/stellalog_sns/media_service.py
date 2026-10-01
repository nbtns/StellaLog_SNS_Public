"""録音した声、ローカル音声合成、FFmpeg動画生成をまとめる処理。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import tempfile
import wave

from .models import AppSettings, PostSet
from .paths import app_data_dir, generated_videos_dir, voice_preview_path
from .pronunciation import correct_pronunciation
from .video_renderer import VideoRenderResult, VideoRenderer, split_subtitle_cards
from .voice_services import (
    NarrationResult,
    NarrationService,
    VoiceProfile,
    VoiceServiceError,
    VoiceboxClient,
    VoicevoxClient,
)


_MBTI_LETTER_READINGS = {
    "I": "アイ",
    "E": "イー",
    "N": "エヌ",
    "S": "エス",
    "F": "エフ",
    "T": "ティー",
    "J": "ジェイ",
    "P": "ピー",
}

_VOICEVOX_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GeneratedMedia:
    video: VideoRenderResult
    narration_provider: str
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedVoicePreview:
    path: Path
    subtitle_durations: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class GeneratedVoiceCardPreview:
    path: Path
    duration: float
    card_index: int


class MediaService:
    """画面から使う、ローカルメディア処理の窓口。"""

    def __init__(
        self,
        settings: AppSettings,
        *,
        video_renderer: VideoRenderer | None = None,
        voicevox_cache_dir: Path | str | None = None,
    ) -> None:
        self.settings = settings
        self.voicebox = VoiceboxClient(settings.voicebox_url)
        self.voicevox = VoicevoxClient(settings.voicevox_url)
        self.video_renderer = video_renderer or VideoRenderer()
        self.voicevox_cache_dir = (
            Path(voicevox_cache_dir)
            if voicevox_cache_dir is not None
            else app_data_dir() / "voicevox_cache"
        )

    def register_voice_sample(
        self,
        wav_path: Path | str,
        reference_text: str,
    ) -> VoiceProfile:
        """録音を既存のVoiceboxプロファイルへ追加し、なければ作成する。"""

        profiles = self.voicebox.list_profiles()
        profile = next(
            (
                item
                for item in profiles
                if self.settings.voicebox_profile_id
                and item.id == self.settings.voicebox_profile_id
            ),
            None,
        )
        if profile is None:
            profile = next(
                (
                    item
                    for item in profiles
                    if item.name.casefold() == self.settings.voicebox_profile_name.casefold()
                ),
                None,
            )
        if profile is None:
            profile = self.voicebox.create_profile(
                self.settings.voicebox_profile_name,
                language="ja",
                default_engine="qwen",
            )
        self.voicebox.add_sample(profile.id, wav_path, reference_text)
        return profile

    def generate_video(
        self,
        post: PostSet,
        *,
        narration_script: str | None = None,
        voice_preview: GeneratedVoicePreview | None = None,
        output_path: Path | str | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> GeneratedMedia:
        """字幕用台本と音声用の読みからTikTok用MP4を順番に作る。"""

        _report(progress, 5, "動画の保存先と背景素材を確認しています")
        videos_dir = generated_videos_dir()
        destination = (
            Path(output_path).resolve()
            if output_path is not None
            else videos_dir / _video_file_name(post)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        voice_script, subtitle_cards, narration_cards = _prepare_voice_scripts(
            post,
            narration_script,
        )

        with tempfile.TemporaryDirectory(
            prefix="stellalog-narration-",
            dir=destination.parent,
        ) as temp_name:
            narration_dir = Path(temp_name)
            narration_path = Path(temp_name) / "narration.wav"
            _report(
                progress,
                -1,
                (
                    "確認済みのVOICEVOX音声を使っています"
                    if voice_preview is not None
                    else "VOICEVOXで字幕ごとのナレーションを作成中です"
                    if self.settings.voice_engine == "voicevox"
                    else "Voiceboxで自分の声のナレーションを作成中です"
                    "（初回や長い台本は数分かかります）"
                ),
            )
            subtitle_durations: tuple[float, ...] | None = None
            if voice_preview is not None:
                if not voice_preview.path.is_file():
                    raise VoiceServiceError(
                        "確認済みのVOICEVOX音声が見つかりません。"
                        "もう一度「① VOICEVOX音声を確認」を押してください。"
                    )
                if len(voice_preview.subtitle_durations) != len(subtitle_cards):
                    raise VoiceServiceError(
                        "確認済み音声と字幕の画面数が一致しません。"
                        "もう一度「① VOICEVOX音声を確認」を押してください。"
                    )
                narration = NarrationResult(voice_preview.path, "voicevox")
                subtitle_durations = voice_preview.subtitle_durations
            elif self.settings.voice_engine == "voicevox":
                narration, subtitle_durations = self._generate_voicevox_segments(
                    narration_cards,
                    narration_dir,
                    narration_path,
                    apply_pronunciation=narration_script is None,
                    progress=progress,
                )
            elif progress is None:
                narration = self._generate_narration(
                    narration_text(
                        voice_script,
                        apply_pronunciation=narration_script is None,
                    ),
                    narration_path,
                )
            else:
                narration = self._generate_narration(
                    narration_text(
                        voice_script,
                        apply_pronunciation=narration_script is None,
                    ),
                    narration_path,
                    progress=progress,
                )
            _report(progress, 55, "ナレーションが完成しました。字幕と背景を準備しています")
            subtitle_options: dict[str, object] = {}
            if subtitle_durations is not None:
                subtitle_options = {
                    "subtitle_cards": subtitle_cards,
                    "subtitle_durations": subtitle_durations,
                }
            if progress is None:
                video = self.video_renderer.render(
                    post.tiktok_script,
                    narration.path,
                    destination,
                    **subtitle_options,
                )
            else:
                video = self.video_renderer.render(
                    post.tiktok_script,
                    narration.path,
                    destination,
                    progress=progress,
                    **subtitle_options,
                )
            _report(progress, 100, "TikTok動画を保存しました")
        return GeneratedMedia(
            video=video,
            narration_provider=narration.provider,
            fallback_reason=narration.fallback_reason,
        )

    def generate_voicevox_preview(
        self,
        post: PostSet,
        *,
        narration_script: str | None = None,
        output_path: Path | str | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> GeneratedVoicePreview:
        """完成動画と同じ区切り・話者設定で確認用VOICEVOX音声を作る。"""

        _report(progress, 5, "確認用の音声を準備しています")
        destination = (
            Path(output_path).resolve()
            if output_path is not None
            else voice_preview_path()
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _voice_script, _subtitle_cards, narration_cards = _prepare_voice_scripts(
            post,
            narration_script,
        )
        with tempfile.TemporaryDirectory(
            prefix="stellalog-preview-",
            dir=destination.parent,
        ) as temp_name:
            narration, durations = self._generate_voicevox_segments(
                narration_cards,
                Path(temp_name),
                destination,
                apply_pronunciation=narration_script is None,
                progress=progress,
            )
        _report(progress, 100, "確認用のVOICEVOX音声ができました")
        return GeneratedVoicePreview(narration.path, durations)

    def generate_voicevox_card_preview(
        self,
        post: PostSet,
        card_index: int,
        *,
        narration_script: str | None = None,
        output_path: Path | str | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> GeneratedVoiceCardPreview:
        """指定した字幕カードだけを、完成動画と同じ設定で読み上げる。"""

        _report(progress, 5, "選んだ字幕の音声を準備しています")
        _voice_script, _subtitle_cards, narration_cards = _prepare_voice_scripts(
            post,
            narration_script,
        )
        if isinstance(card_index, bool) or not isinstance(card_index, int):
            raise VoiceServiceError("確認する字幕の番号が正しくありません。")
        if not 0 <= card_index < len(narration_cards):
            raise VoiceServiceError("確認する字幕が見つかりません。字幕を選び直してください。")
        destination = (
            Path(output_path).resolve()
            if output_path is not None
            else voice_preview_path().with_name("voicevox-card-preview.wav")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="stellalog-card-preview-",
            dir=destination.parent,
        ) as temp_name:
            narration, durations = self._generate_voicevox_segments(
                (narration_cards[card_index],),
                Path(temp_name),
                destination,
                apply_pronunciation=narration_script is None,
                progress=progress,
            )
        _report(progress, 100, "選んだ字幕のVOICEVOX音声ができました")
        return GeneratedVoiceCardPreview(
            path=narration.path,
            duration=durations[0],
            card_index=card_index,
        )

    def _generate_voicevox_segments(
        self,
        cards: tuple[tuple[str, ...], ...],
        working_dir: Path,
        destination: Path,
        *,
        apply_pronunciation: bool = True,
        progress: Callable[[int, str], None] | None = None,
    ) -> tuple[NarrationResult, tuple[float, ...]]:
        """字幕カードと読点ごとに音声を作り、カード単位の実時間も返す。"""

        if not cards:
            raise VoiceServiceError("ナレーションにする字幕がありません。")
        chunks_by_card = tuple(
            tuple(
                chunk.strip()
                for chunk in "".join(card).split("、")
                if chunk.strip()
            )
            for card in cards
        )
        if any(not chunks for chunks in chunks_by_card):
            raise VoiceServiceError("ナレーションにする字幕がありません。")
        segment_paths: list[Path] = []
        total_segments = sum(len(chunks) for chunks in chunks_by_card)
        segment_index = 0
        for chunks in chunks_by_card:
            for chunk in chunks:
                segment_index += 1
                _report(
                    progress,
                    10 + round(40 * (segment_index - 1) / total_segments),
                    (
                        "VOICEVOXでナレーションを作成中です"
                        f"（{segment_index}/{total_segments}）"
                    ),
                )
                # 通常改行は字幕の見た目だけに使い、音声には間を追加しない。
                # 読点は字幕へ表示せず、VOICEVOXへ別々に渡す区切りにする。
                voice_text = narration_text(
                    chunk,
                    apply_pronunciation=apply_pronunciation,
                )
                segment_path = self._get_or_generate_voicevox_segment(
                    voice_text,
                )
                segment_paths.append(segment_path)
        segment_durations = _concatenate_pcm_wavs(segment_paths, destination)
        card_durations: list[float] = []
        duration_index = 0
        for chunks in chunks_by_card:
            next_index = duration_index + len(chunks)
            card_durations.append(sum(segment_durations[duration_index:next_index]))
            duration_index = next_index
        return NarrationResult(destination, "voicevox"), tuple(card_durations)

    def _get_or_generate_voicevox_segment(self, voice_text: str) -> Path:
        """設定と読みが一致する正常なWAVを再利用し、なければ生成する。"""

        cache_key = _voicevox_cache_key(
            text=voice_text,
            voicevox_url=self.settings.voicevox_url,
            speaker_id=self.settings.voicevox_speaker_id,
            speed_scale=self.settings.voicevox_speed_scale,
        )
        cache_path = self.voicevox_cache_dir / cache_key[:2] / f"{cache_key}.wav"
        if _is_valid_pcm_wav(cache_path):
            return cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=f".{cache_key}-",
            suffix=".tmp.wav",
            dir=cache_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        try:
            self.voicevox.generate_wav(
                voice_text,
                temporary_path,
                speaker=self.settings.voicevox_speaker_id,
                speed_scale=self.settings.voicevox_speed_scale,
            )
            if not _is_valid_pcm_wav(temporary_path):
                raise VoiceServiceError(
                    "VOICEVOXから読み取れないWAV音声が返りました。"
                    "VOICEVOXを再起動して、もう一度お試しください。"
                )
            temporary_path.replace(cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return cache_path

    def _generate_narration(
        self,
        text: str,
        destination: Path,
        *,
        progress: Callable[[int, str], None] | None = None,
    ) -> NarrationResult:
        if self.settings.voicevox_fallback_enabled:
            return NarrationService(self.voicebox, self.voicevox).generate_wav(
                text,
                destination,
                voicebox_profile_id=self.settings.voicebox_profile_id,
                voicevox_speaker=self.settings.voicevox_speaker_id,
                voicevox_speed_scale=self.settings.voicevox_speed_scale,
                progress=progress,
            )
        if not self.settings.voicebox_profile_id:
            raise VoiceServiceError(
                "自分の声がまだ登録されていません。先に「自分の声を登録」を押してください。"
            )
        path = self.voicebox.generate_wav(
            text,
            self.settings.voicebox_profile_id,
            destination,
            language="ja",
            engine="qwen",
        )
        return NarrationResult(path=path, provider="voicebox")


def _report(
    progress: Callable[[int, str], None] | None,
    percent: int,
    message: str,
) -> None:
    if progress is not None:
        progress(percent, message)


def _voicevox_cache_key(
    *,
    text: str,
    voicevox_url: str,
    speaker_id: int,
    speed_scale: float,
) -> str:
    """VOICEVOXへ渡す内容と音声設定から安定したキャッシュキーを作る。"""

    payload = {
        "schema_version": _VOICEVOX_CACHE_SCHEMA_VERSION,
        "text": text,
        "voicevox_url": voicevox_url.rstrip("/"),
        "speaker_id": speaker_id,
        "speed_scale": float(speed_scale),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_valid_pcm_wav(path: Path) -> bool:
    """キャッシュを安全に再利用できるPCM WAVか確認する。"""

    if not path.is_file():
        return False
    try:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            frame_count = reader.getnframes()
            if (
                reader.getcomptype() != "NONE"
                or channels < 1
                or sample_width < 1
                or frame_rate < 1
                or frame_count < 1
            ):
                return False
            frames = reader.readframes(frame_count)
            return len(frames) == frame_count * channels * sample_width
    except (EOFError, OSError, wave.Error):
        return False


def _concatenate_pcm_wavs(
    source_paths: list[Path],
    destination: Path,
) -> tuple[float, ...]:
    """同一形式のPCM WAVを順番に連結し、各音声の実時間を返す。"""

    if not source_paths:
        raise VoiceServiceError("連結するナレーション音声がありません。")

    expected_format: tuple[int, int, int, str] | None = None
    chunks: list[bytes] = []
    durations: list[float] = []
    try:
        for source_path in source_paths:
            with wave.open(str(source_path), "rb") as reader:
                channels = reader.getnchannels()
                sample_width = reader.getsampwidth()
                frame_rate = reader.getframerate()
                compression = reader.getcomptype()
                frame_count = reader.getnframes()
                if compression != "NONE" or channels < 1 or sample_width < 1 or frame_rate < 1:
                    raise VoiceServiceError(
                        "VOICEVOXの音声が対応していないWAV形式でした。"
                        "VOICEVOXを再起動して、もう一度お試しください。"
                    )
                if frame_count < 1:
                    raise VoiceServiceError(
                        "VOICEVOXから空の音声が返りました。もう一度お試しください。"
                    )
                current_format = (channels, sample_width, frame_rate, compression)
                if expected_format is None:
                    expected_format = current_format
                elif current_format != expected_format:
                    raise VoiceServiceError(
                        "字幕ごとの音声形式が一致しないため、ナレーションを連結できませんでした。"
                        "VOICEVOXを再起動して、もう一度お試しください。"
                    )
                frames = reader.readframes(frame_count)
                expected_bytes = frame_count * channels * sample_width
                if len(frames) != expected_bytes:
                    raise VoiceServiceError(
                        "VOICEVOXの音声データが途中で切れています。もう一度お試しください。"
                    )
                chunks.append(frames)
                durations.append(frame_count / frame_rate)

        if expected_format is None:  # pragma: no cover - 冒頭で空配列を拒否済み
            raise VoiceServiceError("連結するナレーション音声がありません。")
        temporary = destination.with_name(f".{destination.name}.tmp.wav")
        with wave.open(str(temporary), "wb") as writer:
            writer.setnchannels(expected_format[0])
            writer.setsampwidth(expected_format[1])
            writer.setframerate(expected_format[2])
            writer.setcomptype("NONE", "not compressed")
            for chunk in chunks:
                writer.writeframes(chunk)
        temporary.replace(destination)
    except VoiceServiceError:
        destination.unlink(missing_ok=True)
        raise
    except (EOFError, OSError, wave.Error) as exc:
        destination.unlink(missing_ok=True)
        raise VoiceServiceError(
            "VOICEVOXのWAV音声を読み込めませんでした。"
            "VOICEVOXを再起動して、もう一度お試しください。"
        ) from exc
    finally:
        destination.with_name(f".{destination.name}.tmp.wav").unlink(missing_ok=True)
    return tuple(durations)


def resolve_stellalog_logo(data_dir: Path | str) -> Path:
    """記事データの場所から、StellaLog本体のロゴを読み取り専用で探す。"""

    data_path = Path(data_dir).resolve()
    try:
        web_dir = data_path.parents[1]
    except IndexError as exc:
        raise FileNotFoundError(
            "StellaLogロゴの場所を確認できません。記事フォルダの設定を確認してください。"
        ) from exc
    public_dir = web_dir / "public"
    for name in (
        "stellalog_logo3-4.png",
        "stellalog_logo3.png",
        "stellalog_logo2.png",
        "stellalog_logo.png",
    ):
        candidate = public_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "StellaLogロゴが見つかりません。StellaLog本体のpublicフォルダを確認してください。"
    )


def _video_file_name(post: PostSet) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    article = post.article
    raw = f"{article.concern}-{article.mbti}-{article.zodiac}-{article.gender}"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", raw).strip("-") or "stellalog"
    return f"{stamp}-{safe}.mp4"


def narration_text(script: str, *, apply_pronunciation: bool = True) -> str:
    """字幕用の改行台本を、音声で自然に読める文章へ変換する。"""

    text = correct_pronunciation(script) if apply_pronunciation else script
    text = text.replace("StellaLog", "ステラログ").replace("×", "と")

    def replace_mbti(match: re.Match[str]) -> str:
        return "".join(_MBTI_LETTER_READINGS[letter] for letter in match.group(0))

    text = re.sub(r"(?<![A-Z])[IE][NS][FT][JP](?![A-Z])", replace_mbti, text)
    lines = [line.strip().rstrip("。") for line in text.splitlines() if line.strip()]
    return "。".join(lines) + ("。" if lines else "")


def _prepare_voice_scripts(
    post: PostSet,
    narration_script: str | None,
) -> tuple[str, tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """字幕と音声のカード対応を検査し、共通の生成入力を返す。"""

    voice_script = post.tiktok_script if narration_script is None else narration_script
    if not voice_script.strip():
        raise VoiceServiceError("「音声用の読み」が空です。読みを入力してください。")
    raw_subtitle_cards = _split_cards_on_blank_lines(post.tiktok_script)
    subtitle_cards = split_subtitle_cards(post.tiktok_script)
    if len(subtitle_cards) != len(raw_subtitle_cards):
        raise VoiceServiceError(
            "字幕の1つの区切りが6行を超えるため、音声と正しく合わせられません。"
            "TikTok台本と「音声用の読み」の同じ位置に空白行を入れ、"
            "1画面を6行以内にしてください。"
        )
    narration_cards = _split_cards_on_blank_lines(voice_script)
    if len(narration_cards) != len(subtitle_cards):
        raise VoiceServiceError(
            "字幕と「音声用の読み」の画面数が一致しません。"
            "音声用の読みでは、TikTok台本と同じ位置に空白行を入れてください。"
        )
    return voice_script, subtitle_cards, narration_cards


def _split_cards_on_blank_lines(script: str) -> tuple[tuple[str, ...], ...]:
    """表示幅に影響されず、空白行だけを境界に音声カードを分ける。"""

    normalised = script.replace("\r\n", "\n").replace("\r", "\n")
    cards: list[tuple[str, ...]] = []
    current_lines: list[str] = []
    for source_line in normalised.split("\n"):
        clean = " ".join(source_line.split()).strip()
        if not clean.replace("、", "").strip():
            if current_lines:
                cards.append(tuple(current_lines))
                current_lines = []
            continue
        current_lines.append(clean)
    if current_lines:
        cards.append(tuple(current_lines))
    return tuple(cards)
