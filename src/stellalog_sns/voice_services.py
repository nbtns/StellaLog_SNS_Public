"""ローカル音声合成サービスとの安全な接続処理。

Voicebox と VOICEVOX は、どちらも利用者の PC 内で起動している HTTP API
だけを対象にする。外部ホストへの送信は意図的に拒否する。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import tempfile
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_VOICEBOX_URL = "http://127.0.0.1:17493"
DEFAULT_VOICEVOX_URL = "http://127.0.0.1:50021"
MAX_SCRIPT_CHARS = 5_000
MAX_SAMPLE_BYTES = 50 * 1024 * 1024


class VoiceServiceError(RuntimeError):
    """画面にそのまま出せる、音声サービス用の日本語エラー。"""


class _Response(Protocol):
    headers: Any

    def read(self) -> bytes: ...

    def __enter__(self) -> "_Response": ...

    def __exit__(self, *args: object) -> None: ...


Transport = Callable[[Request, float], _Response]


class _NoRedirectHandler(HTTPRedirectHandler):
    """ローカル API から外部 URL へ誘導されることを防ぐ。"""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_LOCAL_OPENER = build_opener(_NoRedirectHandler())


def _default_transport(request: Request, timeout: float) -> _Response:
    return _LOCAL_OPENER.open(request, timeout=timeout)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    id: str
    name: str
    language: str = "ja"
    sample_count: int = 0
    default_engine: str | None = None


@dataclass(frozen=True, slots=True)
class NarrationResult:
    path: Path
    provider: str
    fallback_reason: str | None = None


def _normalise_local_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("音声サービスのURLが正しくありません。") from exc

    if parsed.scheme.lower() != "http":
        raise ValueError("音声サービスはPC内の http URLだけ指定できます。")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("音声サービスは localhost または 127.0.0.1 だけ指定できます。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("音声サービスのURLに認証情報や追加パラメータは指定できません。")
    if parsed.path not in {"", "/"}:
        raise ValueError("音声サービスのURLにはポート番号までを指定してください。")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("音声サービスのポート番号が正しくありません。")
    return urlunsplit(("http", parsed.netloc, "", "", ""))


def _validate_text(text: str, *, label: str = "台本") -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{label}が空です。内容を入力してください。")
    cleaned = text.strip()
    if len(cleaned) > MAX_SCRIPT_CHARS:
        raise ValueError(f"{label}が長すぎます。{MAX_SCRIPT_CHARS:,}文字以内にしてください。")
    return cleaned


def _safe_output_path(output_path: str | Path) -> Path:
    path = Path(output_path).expanduser()
    if not path.is_absolute():
        raise ValueError("音声の保存先は絶対パスで指定してください。")
    path = path.resolve(strict=False)
    if str(path).startswith("\\\\"):
        raise ValueError("音声はPC内のフォルダーに保存してください。")
    if path.suffix.lower() != ".wav":
        raise ValueError("音声の保存先は .wav ファイルを指定してください。")
    if path.exists() and not path.is_file():
        raise ValueError("音声の保存先にフォルダーは指定できません。")
    if not path.parent.is_dir():
        raise ValueError("音声の保存先フォルダーが見つかりません。")
    return path


def _validate_wav_bytes(data: bytes, *, service_name: str) -> None:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceServiceError(
            f"{service_name}から正しいWAV音声を受け取れませんでした。"
            "サービスを再起動して、もう一度お試しください。"
        )


def _write_wav_atomically(path: Path, data: bytes) -> None:
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".wav", prefix=".narration-", dir=path.parent, delete=False
        ) as file:
            temporary = file.name
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise VoiceServiceError(
            "WAV音声を保存できませんでした。保存先を変更するか、"
            "ほかのアプリでファイルを開いていないか確認してください。"
        ) from exc
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def _extract_http_detail(error: HTTPError) -> str | None:
    try:
        body = error.read(16_384)
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:300]
    return None


class _LocalJsonClient:
    service_name = "音声サービス"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        if timeout <= 0 or timeout > 3_600:
            raise ValueError("通信の待ち時間は1時間以内で指定してください。")
        self.base_url = _normalise_local_base_url(base_url)
        self.timeout = float(timeout)
        self._transport = transport or _default_transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[bytes, str]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("音声サービスへの接続先が正しくありません。")
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            with self._transport(request, timeout or self.timeout) as response:
                body = response.read()
                content_type = str(response.headers.get("Content-Type", ""))
                return body, content_type
        except HTTPError as exc:
            detail = _extract_http_detail(exc)
            suffix = f" 詳細: {detail}" if detail else ""
            raise VoiceServiceError(
                f"{self.service_name}が処理を完了できませんでした（HTTP {exc.code}）。{suffix}"
            ) from exc
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise VoiceServiceError(
                f"{self.service_name}に接続できません。アプリが起動しているか確認してください。"
            ) from exc

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {**(headers or {}), "Content-Type": "application/json"}
        body, _ = self._request(
            method, path, data=data, headers=headers, timeout=timeout
        )
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VoiceServiceError(
                f"{self.service_name}から読み取れない応答が返りました。サービスを再起動してください。"
            ) from exc


class VoiceboxClient(_LocalJsonClient):
    """Voicebox 0.5 系のローカル REST API クライアント。"""

    service_name = "Voicebox"

    def __init__(
        self,
        base_url: str = DEFAULT_VOICEBOX_URL,
        *,
        timeout: float = 10.0,
        generation_timeout: float = 900.0,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(base_url, timeout=timeout, transport=transport)
        if generation_timeout <= 0 or generation_timeout > 3_600:
            raise ValueError("音声生成の待ち時間は1時間以内で指定してください。")
        self.generation_timeout = float(generation_timeout)

    def is_available(self) -> bool:
        try:
            payload = self._json_request("GET", "/health")
        except VoiceServiceError:
            return False
        return isinstance(payload, dict) and payload.get("status") in {
            "ok",
            "healthy",
            "ready",
        }

    def list_profiles(self) -> list[VoiceProfile]:
        payload = self._json_request("GET", "/profiles")
        rows: Any = payload
        if isinstance(payload, dict):
            for key in ("items", "profiles", "data"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        if not isinstance(rows, list):
            raise VoiceServiceError("Voiceboxの声一覧を読み取れませんでした。")
        profiles: list[VoiceProfile] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            profile_id = row.get("id") or row.get("profile_id")
            name = row.get("name") or row.get("display_name")
            if not isinstance(profile_id, str) or not isinstance(name, str):
                continue
            sample_count = row.get("sample_count", 0)
            profiles.append(
                VoiceProfile(
                    id=profile_id,
                    name=name,
                    language=str(row.get("language") or "ja"),
                    sample_count=sample_count if isinstance(sample_count, int) else 0,
                    default_engine=(
                        str(row["default_engine"])
                        if row.get("default_engine") is not None
                        else None
                    ),
                )
            )
        return profiles

    def create_profile(
        self,
        name: str,
        *,
        language: str = "ja",
        description: str = "StellaLog SNS Studioで録音した声",
        default_engine: str = "qwen",
    ) -> VoiceProfile:
        name = _validate_text(name, label="声の名前")
        if len(name) > 100:
            raise ValueError("声の名前は100文字以内にしてください。")
        if language != "ja":
            raise ValueError("現在は日本語の声だけ登録できます。")
        payload = self._json_request(
            "POST",
            "/profiles",
            payload={
                "name": name,
                "description": description[:500],
                "language": language,
                "voice_type": "cloned",
                "default_engine": default_engine,
            },
        )
        if isinstance(payload, dict) and isinstance(payload.get("profile"), dict):
            payload = payload["profile"]
        if not isinstance(payload, dict):
            raise VoiceServiceError("Voiceboxで声を作成できましたが、登録結果を読み取れませんでした。")
        profile_id = payload.get("id") or payload.get("profile_id")
        profile_name = payload.get("name") or name
        if not isinstance(profile_id, str):
            raise VoiceServiceError("Voiceboxから声の識別番号を受け取れませんでした。")
        sample_count = payload.get("sample_count", 0)
        return VoiceProfile(
            id=profile_id,
            name=str(profile_name),
            language=str(payload.get("language") or language),
            sample_count=sample_count if isinstance(sample_count, int) else 0,
            default_engine=(
                str(payload["default_engine"])
                if payload.get("default_engine") is not None
                else default_engine
            ),
        )

    def add_sample(
        self,
        profile_id: str,
        wav_path: str | Path,
        reference_text: str,
    ) -> dict[str, Any]:
        profile_id = _validate_text(profile_id, label="声の識別番号")
        reference_text = _validate_text(reference_text, label="録音した文章")
        if len(reference_text) > 1_000:
            raise ValueError("録音した文章は1,000文字以内にしてください。")
        path = Path(wav_path).expanduser().resolve(strict=False)
        if str(path).startswith("\\\\"):
            raise ValueError("登録する録音はPC内のWAVファイルを選んでください。")
        if not path.is_file() or path.suffix.lower() != ".wav":
            raise ValueError("登録する録音WAVファイルが見つかりません。")
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ValueError("登録する録音WAVファイルを読み取れません。") from exc
        if size <= 0 or size > MAX_SAMPLE_BYTES:
            raise ValueError("録音WAVは空でない50MB以下のファイルを選んでください。")
        try:
            with path.open("rb") as file:
                audio = file.read()
        except OSError as exc:
            raise ValueError("登録する録音WAVファイルを読み取れません。") from exc
        _validate_wav_bytes(audio, service_name="録音ファイル")

        boundary = f"----StellaLogSNS{secrets.token_hex(16)}"
        body = self._multipart_body(
            boundary,
            reference_text=reference_text,
            audio=audio,
        )
        payload = self._json_request(
            "POST",
            f"/profiles/{quote(profile_id, safe='')}/samples",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=max(self.timeout, 60.0),
        )
        if isinstance(payload, dict) and isinstance(payload.get("sample"), dict):
            payload = payload["sample"]
        if not isinstance(payload, dict):
            raise VoiceServiceError("Voiceboxで録音を登録できましたが、結果を読み取れませんでした。")
        return payload

    @staticmethod
    def _multipart_body(boundary: str, *, reference_text: str, audio: bytes) -> bytes:
        marker = boundary.encode("ascii")
        return b"".join(
            (
                b"--" + marker + b"\r\n",
                b'Content-Disposition: form-data; name="reference_text"\r\n\r\n',
                reference_text.encode("utf-8"),
                b"\r\n--" + marker + b"\r\n",
                b'Content-Disposition: form-data; name="file"; filename="sample.wav"\r\n',
                b"Content-Type: audio/wav\r\n\r\n",
                audio,
                b"\r\n--" + marker + b"--\r\n",
            )
        )

    def generate_wav(
        self,
        text: str,
        profile_id: str,
        output_path: str | Path,
        *,
        language: str = "ja",
        engine: str = "qwen",
    ) -> Path:
        text = _validate_text(text)
        profile_id = _validate_text(profile_id, label="声の識別番号")
        path = _safe_output_path(output_path)
        body, _ = self._request(
            "POST",
            "/generate/stream",
            data=json.dumps(
                {
                    "profile_id": profile_id,
                    "text": text,
                    "language": language,
                    "engine": engine,
                    "normalize": True,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            timeout=self.generation_timeout,
        )
        _validate_wav_bytes(body, service_name="Voicebox")
        _write_wav_atomically(path, body)
        return path


class VoicevoxClient(_LocalJsonClient):
    """VOICEVOX Engine のローカル REST API クライアント。"""

    service_name = "VOICEVOX"

    def __init__(
        self,
        base_url: str = DEFAULT_VOICEVOX_URL,
        *,
        timeout: float = 10.0,
        generation_timeout: float = 300.0,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(base_url, timeout=timeout, transport=transport)
        if generation_timeout <= 0 or generation_timeout > 3_600:
            raise ValueError("音声生成の待ち時間は1時間以内で指定してください。")
        self.generation_timeout = float(generation_timeout)

    def is_available(self) -> bool:
        try:
            body, _ = self._request("GET", "/version")
        except VoiceServiceError:
            return False
        return bool(body.strip())

    def generate_wav(
        self,
        text: str,
        output_path: str | Path,
        *,
        speaker: int = 3,
        speed_scale: float = 1.0,
    ) -> Path:
        text = _validate_text(text)
        path = _safe_output_path(output_path)
        if isinstance(speaker, bool) or not isinstance(speaker, int) or speaker < 0:
            raise ValueError("VOICEVOXの話者番号が正しくありません。")
        if (
            isinstance(speed_scale, bool)
            or not isinstance(speed_scale, (int, float))
            or not 0.5 <= float(speed_scale) <= 2.0
        ):
            raise ValueError("VOICEVOXの音声速度は0.50〜2.00倍で指定してください。")
        parameters = urlencode({"text": text, "speaker": speaker})
        query = self._json_request(
            "POST",
            f"/audio_query?{parameters}",
            data=b"",
            timeout=self.generation_timeout,
        )
        if not isinstance(query, dict):
            raise VoiceServiceError("VOICEVOXの読み上げ設定を読み取れませんでした。")
        query["speedScale"] = float(speed_scale)
        body, _ = self._request(
            "POST",
            f"/synthesis?{urlencode({'speaker': speaker})}",
            data=json.dumps(query, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            timeout=self.generation_timeout,
        )
        _validate_wav_bytes(body, service_name="VOICEVOX")
        _write_wav_atomically(path, body)
        return path


class NarrationService:
    """自分の声を優先し、失敗したときだけVOICEVOXへ切り替える。"""

    def __init__(
        self,
        voicebox: VoiceboxClient | None = None,
        voicevox: VoicevoxClient | None = None,
    ) -> None:
        self.voicebox = voicebox or VoiceboxClient()
        self.voicevox = voicevox or VoicevoxClient()

    def generate_wav(
        self,
        text: str,
        output_path: str | Path,
        *,
        voicebox_profile_id: str | None,
        voicevox_speaker: int = 3,
        voicevox_speed_scale: float = 1.0,
        voicebox_engine: str = "qwen",
        progress: Callable[[int, str], None] | None = None,
    ) -> NarrationResult:
        text = _validate_text(text)
        path = _safe_output_path(output_path)
        voicebox_error: str | None = None
        if voicebox_profile_id and voicebox_profile_id.strip():
            try:
                result = self.voicebox.generate_wav(
                    text,
                    voicebox_profile_id,
                    path,
                    language="ja",
                    engine=voicebox_engine,
                )
                return NarrationResult(path=result, provider="voicebox")
            except VoiceServiceError as exc:
                voicebox_error = str(exc)
        else:
            voicebox_error = "自分の声がまだ選ばれていません。"

        if progress is not None:
            progress(
                -1,
                "Voiceboxを使えなかったため、予備のVOICEVOXでナレーションを作成中です",
            )
        try:
            result = self.voicevox.generate_wav(
                text,
                path,
                speaker=voicevox_speaker,
                speed_scale=voicevox_speed_scale,
            )
        except VoiceServiceError as exc:
            raise VoiceServiceError(
                "ナレーションを作れませんでした。VoiceboxとVOICEVOXを起動してから、"
                f"もう一度お試しください。Voicebox: {voicebox_error} VOICEVOX: {exc}"
            ) from exc
        return NarrationResult(
            path=result,
            provider="voicevox",
            fallback_reason=voicebox_error,
        )
