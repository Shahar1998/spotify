import json
import time
from pathlib import Path

import requests


DEFAULT_CACHE_PATH = Path('.lyrics_cache.json')
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def _cache_key(track_name, artist_name):
    return f'{track_name.strip().casefold()}::{artist_name.strip().casefold()}'


def _load_cache(cache_path):
    try:
        with Path(cache_path).open('r', encoding='utf-8') as cache_file:
            data = json.load(cache_file)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache_path, cache):
    try:
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + '.tmp')
        with temporary_path.open('w', encoding='utf-8') as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False, indent=2)
        temporary_path.replace(path)
    except OSError:
        # A cache failure must not prevent the game from running.
        pass


def fetch_lrclib_lyrics(
    track_name,
    artist_name,
    session=None,
    cache_path=DEFAULT_CACHE_PATH,
    max_attempts=3,
):
    """Fetch and cache plain lyrics from LRCLIB with retry handling."""
    cache = _load_cache(cache_path)
    key = _cache_key(track_name, artist_name)
    if key in cache:
        return cache[key]

    owns_session = session is None
    http = session or requests.Session()
    request_url = 'https://lrclib.net/api/get'
    request_params = {
        'track_name': track_name,
        'artist_name': artist_name,
    }
    request_headers = {
        'User-Agent': 'SpotiWord/0.1.0',
    }

    try:
        for attempt in range(max_attempts):
            try:
                response = http.get(
                    request_url,
                    params=request_params,
                    headers=request_headers,
                    timeout=5,
                )

                if response.status_code == 200:
                    data = response.json()
                    lyrics = data.get('plainLyrics')
                    result = lyrics.strip() if isinstance(lyrics, str) else None
                    cache[key] = result
                    _save_cache(cache_path, cache)
                    return result

                if response.status_code == 404:
                    cache[key] = None
                    _save_cache(cache_path, cache)
                    return None

                if response.status_code not in RETRY_STATUS_CODES:
                    break
            except (requests.RequestException, ValueError):
                pass

            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
    finally:
        if owns_session:
            http.close()

    cache[key] = None
    _save_cache(cache_path, cache)
    return None
