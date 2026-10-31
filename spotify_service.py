import math
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import ENV_PATH, SPOTIFY_CACHE_PATH
from core import is_hebrew
from lyrics_client import LyricsCache, fetch_lrclib_lyrics
from models import Song


dotenv.load_dotenv(ENV_PATH)


class LoadingCancelled(Exception):
    """Raised when the user cancels library loading."""


def create_spotify_client():
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')
    missing = [
        name for name, value in (
            ('SPOTIFY_CLIENT_ID', client_id),
            ('SPOTIFY_CLIENT_SECRET', client_secret),
            ('SPOTIFY_REDIRECT_URI', redirect_uri),
        ) if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Spotify configuration: {', '.join(missing)}")
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope='user-library-read',
        cache_path=str(SPOTIFY_CACHE_PATH),
    ))


def clean_track_name(name):
    name = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with)\b.*?[\)\]]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[\(\[]\s*remix\b.*?[\)\]]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*[-–]\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|radio edit|acoustic)\b.*$', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', name).strip(' -–')


def _build_song_entry(item, lyrics_cache=None):
    track = item.get('track')
    if not track or not track.get('artists'):
        return None
    original_name = track.get('name', '')
    artist_name = track['artists'][0].get('name', '')
    album_images = track.get('album', {}).get('images', [])
    lyrics = fetch_lrclib_lyrics(clean_track_name(original_name), artist_name, cache=lyrics_cache)
    has_real_lyrics = bool(lyrics)
    return Song(
        track_name=original_name,
        artist=artist_name,
        spotify_url=track.get('external_urls', {}).get('spotify', ''),
        lyrics=lyrics if has_real_lyrics else f'{original_name} {artist_name}',
        has_real_lyrics=has_real_lyrics,
        album_art_url=album_images[0].get('url') if album_images else None,
    ), is_hebrew(original_name) or is_hebrew(artist_name)


def load_and_categorize_songs(spotify_client, max_songs=100, progress_callback=None, cancel_callback=None):
    page_size = 50
    metadata = spotify_client.current_user_saved_tracks(limit=1, offset=0)
    total_tracks = metadata.get('total', len(metadata.get('items', [])))
    total_pages = max(1, math.ceil(total_tracks / page_size))
    pages_needed = min(total_pages, max(1, math.ceil(max_songs / page_size) + 1))
    selected_pages = random.sample(range(total_pages), pages_needed)
    items = []
    for page_number in selected_pages:
        if cancel_callback and cancel_callback():
            raise LoadingCancelled()
        page = spotify_client.current_user_saved_tracks(limit=page_size, offset=page_number * page_size)
        items.extend(page.get('items', []))

    unique_items = {}
    for item in items:
        track = item.get('track') or {}
        unique_items[track.get('id') or f"{track.get('name')}::{track.get('uri')}"] = item
    selected_items = random.sample(list(unique_items.values()), min(max_songs, len(unique_items)))
    if progress_callback:
        progress_callback(0, len(selected_items), f'Selected {len(selected_items)} random tracks')

    english_songs, hebrew_songs = [], []
    lyrics_cache = LyricsCache()
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(_build_song_entry, item, lyrics_cache) for item in selected_items]
            for number, future in enumerate(as_completed(futures), 1):
                if cancel_callback and cancel_callback():
                    for pending in futures:
                        pending.cancel()
                    raise LoadingCancelled()
                result = future.result()
                if progress_callback:
                    progress_callback(number, len(selected_items), f'Fetching lyrics: {number}/{len(selected_items)}')
                if result:
                    song, hebrew = result
                    (hebrew_songs if hebrew else english_songs).append(song)
    finally:
        lyrics_cache.flush()
    return english_songs, hebrew_songs
