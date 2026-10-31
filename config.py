import os
import sys
import logging
from pathlib import Path

import dotenv


APP_NAME = "SpotiWord"


def application_directory():
    """Return the directory containing the source or packaged executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_directory():
    """Return the directory where PyInstaller bundles read-only resources."""
    bundled_directory = getattr(sys, "_MEIPASS", None)
    if bundled_directory:
        return Path(bundled_directory)
    return application_directory()


def user_data_directory():
    """Return a writable per-user directory for tokens and caches."""
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / APP_NAME


ENV_PATH = application_directory() / ".env"
USER_DATA_PATH = user_data_directory()
SPOTIFY_CACHE_PATH = USER_DATA_PATH / "spotify.cache"
LYRICS_CACHE_PATH = USER_DATA_PATH / "lyrics_cache.json"
LOG_PATH = USER_DATA_PATH / "spotiword.log"
REQUIRED_CONFIG_KEYS = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REDIRECT_URI",
)


def missing_configuration():
    return [key for key in REQUIRED_CONFIG_KEYS if not os.getenv(key)]


def save_configuration(values):
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = ENV_PATH.with_suffix(".tmp")
    content = "\n".join(f"{key}={values.get(key, '').strip()}" for key in REQUIRED_CONFIG_KEYS) + "\n"
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(ENV_PATH)
    dotenv.load_dotenv(ENV_PATH, override=True)


def configure_logging():
    USER_DATA_PATH.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
