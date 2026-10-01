from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "StellaLogSNSStudio" / "public-demo"
    return Path.home() / "AppData" / "Local" / "StellaLogSNSStudio" / "public-demo"


def voice_samples_dir() -> Path:
    """本人の声として採用した録音を保存する場所。"""

    return app_data_dir() / "voice_samples"


def generated_videos_dir() -> Path:
    """完成したTikTok動画を保存する場所。"""

    return app_data_dir() / "videos"


def voice_preview_path() -> Path:
    """動画作成前に確認するVOICEVOX音声の保存先。"""

    return app_data_dir() / "audio_previews" / "voicevox-preview.wav"
