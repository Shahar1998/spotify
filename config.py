import os
import sys
from pathlib import Path


APP_NAME = "SpotiWord"


def application_directory():
    """Return the directory containing the source or packaged executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_directory():
    """Return a writable per-user directory for tokens and caches."""
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / APP_NAME


ENV_PATH = application_directory() / ".env"
USER_DATA_PATH = user_data_directory()
SPOTIFY_CACHE_PATH = USER_DATA_PATH / "spotify.cache"
LYRICS_CACHE_PATH = USER_DATA_PATH / "lyrics_cache.json"
