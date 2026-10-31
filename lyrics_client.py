import json
import time
from pathlib import Path
from threading import Lock, local

import requests


DEFAULT_CACHE_PATH = Path('.lyrics_cache.json')
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
NEGATIVE_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_LOCK = Lock()
_THREAD_LOCAL = local()
_MISSING = object()


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
        with _CACHE_LOCK:
            path = Path(cache_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            merged_cache = _load_cache(path)
            merged_cache.update(cache)
            temporary_path = path.with_suffix(path.suffix + '.tmp')
            with temporary_path.open('w', encoding='utf-8') as cache_file:
                json.dump(merged_cache, cache_file, ensure_ascii=False, indent=2)
            temporary_path.replace(path)
    except OSError:
        # A cache failure must not prevent the game from running.
        pass


class LyricsCache:
    """In-memory lyric cache that can be flushed once after a batch."""

    def __init__(self, cache_path=DEFAULT_CACHE_PATH):
        self.cache_path = Path(cache_path)
        self.data = _load_cache(self.cache_path)
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            if key not in self.data:
                return _MISSING
            value = self.data[key]
            if isinstance(value, dict):
                lyrics = value.get('lyrics')
                cached_at = value.get('cached_at', 0)
                if lyrics or time.time() - cached_at < NEGATIVE_CACHE_TTL_SECONDS:
                    return lyrics
                del self.data[key]
                return _MISSING
            return value

    def set(self, key, lyrics):
        with self.lock:
            self.data[key] = {'lyrics': lyrics, 'cached_at': time.time()}

    def flush(self):
        with self.lock:
            _save_cache(self.cache_path, self.data)


def _get_thread_session():
    if not hasattr(_THREAD_LOCAL, 'session'):
        _THREAD_LOCAL.session = requests.Session()
    return _THREAD_LOCAL.session


def fetch_lrclib_lyrics(
    track_name,
    artist_name,
    session=None,
    cache_path=DEFAULT_CACHE_PATH,
    cache=None,
    max_attempts=3,
):
    """Fetch and cache plain lyrics from LRCLIB with retry handling."""
    key = _cache_key(track_name, artist_name)
    owns_cache = cache is None
    lyric_cache = cache or LyricsCache(cache_path)
    cached_lyrics = lyric_cache.get(key)
    if cached_lyrics is not _MISSING:
        return cached_lyrics

    http = session or _get_thread_session()
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
                    lyric_cache.set(key, result)
                    if owns_cache:
                        lyric_cache.flush()
                    return result

                if response.status_code == 404:
                    lyric_cache.set(key, None)
                    if owns_cache:
                        lyric_cache.flush()
                    return None

                if response.status_code not in RETRY_STATUS_CODES:
                    break
            except (requests.RequestException, ValueError):
                pass

            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
    finally:
        pass

    lyric_cache.set(key, None)
    if owns_cache:
        lyric_cache.flush()
    return None
