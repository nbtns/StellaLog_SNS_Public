"""アプリ設定のローカル保存。

設定ファイルが壊れていてもアプリを起動できるよう、読み取れないファイルは
``recovery`` フォルダへ残し、既定値へ戻します。
"""

from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .models import AppSettings
from .paths import app_data_dir


APP_DIRECTORY_NAME = "StellaLogSNSStudio"
SETTINGS_FILE_NAME = "settings.json"


def default_app_data_dir() -> Path:
    """ユーザーごとのアプリ保存先を返します。"""

    return app_data_dir()


class SettingsStore:
    """``AppSettings`` をJSONとして安全に読み書きします。"""

    def __init__(self, app_dir: Path | str | None = None) -> None:
        self.app_dir = Path(app_dir) if app_dir is not None else default_app_data_dir()
        self.path = self.app_dir / SETTINGS_FILE_NAME
        self.recovery_dir = self.app_dir / "recovery"

    def load(self) -> AppSettings:
        """設定を読み込みます。未作成・破損時は既定値を返します。"""

        if not self.path.exists():
            return AppSettings()

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("設定ファイルのルートがオブジェクトではありません")
            return self._from_dict(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self._move_to_recovery(self.path, "settings-corrupt", ".json")
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        """設定を一時ファイル経由で保存し、書き込み途中の破損を防ぎます。"""

        self.app_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(settings)
        for field in fields(settings):
            value = payload.get(field.name)
            if isinstance(value, Path):
                payload[field.name] = str(value)

        temporary_path = self.path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)

    def _from_dict(self, raw: dict[str, Any]) -> AppSettings:
        known_fields = {field.name: field for field in fields(AppSettings)}
        values: dict[str, Any] = {}
        for name, value in raw.items():
            field = known_fields.get(name)
            if field is None:
                # 将来版の項目を旧版が読んでも起動できるよう無視します。
                continue
            if name == "data_dir":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("記事フォルダが不正です")
                values[name] = Path(value)
            elif name == "voicevox_speed_scale":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("VOICEVOXの音声速度が不正です")
                speed = float(value)
                if not 0.5 <= speed <= 2.0:
                    raise ValueError("VOICEVOXの音声速度が範囲外です")
                values[name] = speed
            else:
                values[name] = value
        return AppSettings(**values)

    def _move_to_recovery(self, source: Path, prefix: str, suffix: str) -> Path | None:
        if not source.exists():
            return None
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.recovery_dir / f"{prefix}-{stamp}{suffix}"
        shutil.move(str(source), str(destination))
        return destination
