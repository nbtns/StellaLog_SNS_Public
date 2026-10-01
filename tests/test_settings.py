from dataclasses import replace
from pathlib import Path

from stellalog_sns.models import AppSettings
from stellalog_sns.settings import SettingsStore, default_app_data_dir


def test_default_app_data_dir_uses_localappdata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert default_app_data_dir() == tmp_path / "StellaLogSNSStudio" / "public-demo"


def test_settings_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    expected = replace(
        AppSettings(),
        data_dir=tmp_path / "articles",
        site_origin="https://example.test",
        reading_chars_per_minute=300,
        voicebox_profile_id="profile-123",
        voice_sample_path=str(tmp_path / "voice.wav"),
        voicevox_speaker_id=8,
        voicevox_speed_scale=1.25,
        weekly_quotas={"personality": 2, "love": 1},
    )

    store.save(expected)

    assert store.load() == expected
    assert '"data_dir"' in store.path.read_text(encoding="utf-8")


def test_missing_settings_returns_defaults_without_creating_file(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)

    assert store.load() == AppSettings()
    assert not store.path.exists()


def test_corrupt_settings_is_preserved_and_defaults_are_returned(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken", encoding="utf-8")

    loaded = store.load()

    assert loaded == AppSettings()
    assert not store.path.exists()
    recovered = list((tmp_path / "recovery").glob("settings-corrupt-*.json"))
    assert len(recovered) == 1
    assert recovered[0].read_text(encoding="utf-8") == "{broken"


def test_unknown_future_setting_is_ignored(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        '{"data_dir": "C:/articles", "future_option": true}',
        encoding="utf-8",
    )

    loaded = store.load()

    assert loaded.data_dir == Path("C:/articles")


def test_invalid_voicevox_speed_recovers_settings(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        '{"data_dir": "C:/articles", "voicevox_speed_scale": 3.0}',
        encoding="utf-8",
    )

    loaded = store.load()

    assert loaded == AppSettings()
    assert not store.path.exists()
