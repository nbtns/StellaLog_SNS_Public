from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.error import URLError

import pytest

from stellalog_sns.voice_services import (
    NarrationService,
    VoiceServiceError,
    VoiceboxClient,
    VoicevoxClient,
)


WAV = b"RIFF\x04\x00\x00\x00WAVEdata"


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self._body = io.BytesIO(body)
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def json_response(payload: object) -> FakeResponse:
    return FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def test_voicebox_health_and_wrapped_profile_list_are_supported() -> None:
    requests = []

    def transport(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/health"):
            return json_response({"status": "healthy"})
        return json_response(
            {
                "items": [
                    {
                        "profile_id": "profile-1",
                        "display_name": "わたしの声",
                        "language": "ja",
                        "sample_count": 3,
                    }
                ]
            }
        )

    client = VoiceboxClient(transport=transport)

    assert client.is_available() is True
    assert client.list_profiles()[0].name == "わたしの声"
    assert requests[1][0].full_url == "http://127.0.0.1:17493/profiles"


def test_voicebox_create_profile_and_add_wav_sample(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample.wav"
    sample_path.write_bytes(WAV)
    requests = []

    def transport(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/profiles"):
            return json_response(
                {
                    "id": "profile/unsafe",
                    "name": "わたしの声",
                    "language": "ja",
                    "sample_count": 0,
                }
            )
        return json_response({"sample": {"id": "sample-1"}})

    client = VoiceboxClient(transport=transport)
    profile = client.create_profile("わたしの声")
    result = client.add_sample(profile.id, sample_path, "これは録音した文章です")

    assert profile.id == "profile/unsafe"
    assert result["id"] == "sample-1"
    assert requests[1].full_url.endswith("/profiles/profile%2Funsafe/samples")
    content_type = requests[1].headers["Content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="reference_text"' in requests[1].data
    assert "これは録音した文章です".encode() in requests[1].data
    assert WAV in requests[1].data


def test_voicebox_generates_wav_atomically(tmp_path: Path) -> None:
    output = tmp_path / "narration.wav"

    def transport(request, timeout):
        assert request.full_url.endswith("/generate/stream")
        assert timeout == 900.0
        payload = json.loads(request.data.decode())
        assert payload["language"] == "ja"
        assert payload["profile_id"] == "profile-1"
        return FakeResponse(WAV, "audio/wav")

    result = VoiceboxClient(transport=transport).generate_wav(
        "今日の星占いです", "profile-1", output
    )

    assert result == output.resolve()
    assert output.read_bytes() == WAV


def test_narration_falls_back_to_voicevox(tmp_path: Path) -> None:
    output = tmp_path / "fallback.wav"
    voicevox_requests = []

    def voicebox_transport(request, timeout):
        raise URLError("not running")

    def voicevox_transport(request, timeout):
        voicevox_requests.append(request)
        if "/audio_query?" in request.full_url:
            return json_response({"speedScale": 1.0, "accent_phrases": []})
        return FakeResponse(WAV, "audio/wav")

    service = NarrationService(
        VoiceboxClient(transport=voicebox_transport),
        VoicevoxClient(transport=voicevox_transport),
    )

    result = service.generate_wav(
        "今日の星占いです",
        output,
        voicebox_profile_id="profile-1",
        voicevox_speaker=3,
        voicevox_speed_scale=1.2,
    )

    assert result.provider == "voicevox"
    assert "Voiceboxに接続できません" in (result.fallback_reason or "")
    assert output.read_bytes() == WAV
    assert "/audio_query?" in voicevox_requests[0].full_url
    assert voicevox_requests[1].full_url.endswith("/synthesis?speaker=3")
    synthesis_payload = json.loads(voicevox_requests[1].data.decode("utf-8"))
    assert synthesis_payload["speedScale"] == 1.2


@pytest.mark.parametrize("speed", [0.49, 2.01, True, "1.2"])
def test_voicevox_rejects_invalid_speed(speed, tmp_path: Path) -> None:
    client = VoicevoxClient(
        transport=lambda request, timeout: json_response(
            {"speedScale": 1.0, "accent_phrases": []}
        )
    )

    with pytest.raises(ValueError, match="0.50〜2.00"):
        client.generate_wav(
            "台本",
            tmp_path / "voice.wav",
            speaker=46,
            speed_scale=speed,
        )


def test_narration_reports_both_services_when_fallback_also_fails(
    tmp_path: Path,
) -> None:
    def unavailable(request, timeout):
        raise URLError("not running")

    service = NarrationService(
        VoiceboxClient(transport=unavailable),
        VoicevoxClient(transport=unavailable),
    )

    with pytest.raises(VoiceServiceError, match="VoiceboxとVOICEVOXを起動"):
        service.generate_wav(
            "今日の星占いです",
            tmp_path / "failed.wav",
            voicebox_profile_id="profile-1",
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:17493",
        "http://example.com:17493",
        "http://localhost:17493/api",
        "http://user:pass@localhost:17493",
    ],
)
def test_remote_or_ambiguous_service_urls_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        VoiceboxClient(url)


def test_output_must_be_an_absolute_wav_path(tmp_path: Path) -> None:
    client = VoiceboxClient(transport=lambda request, timeout: FakeResponse(WAV, "audio/wav"))

    with pytest.raises(ValueError, match="絶対パス"):
        client.generate_wav("台本", "profile-1", Path("relative.wav"))

    with pytest.raises(ValueError, match=".wav"):
        client.generate_wav("台本", "profile-1", tmp_path / "audio.mp3")
