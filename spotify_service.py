import math
import logging
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import dotenv
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from config import ENV_PATH, SPOTIFY_CACHE_PATH
from core import GENRE_FILTERS, is_hebrew
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
        scope='user-library-read playlist-read-private playlist-read-collaborative user-read-playback-state user-modify-playback-state',
        cache_path=str(SPOTIFY_CACHE_PATH),
    ))


def list_spotify_sources(spotify_client):
    """Return selectable Spotify libraries and playlists."""
    sources = [
        {'id': None, 'name': 'Spotify Catalog', 'kind': 'catalog'},
        {'id': None, 'name': 'Liked Songs', 'kind': 'liked'},
    ]
    results = spotify_client.current_user_playlists(limit=50)
    while results:
        for playlist in results.get('items', []):
            if playlist and playlist.get('id'):
                sources.append({
                    'id': playlist['id'],
                    'name': playlist.get('name', 'Unnamed playlist'),
                    'kind': 'playlist',
                })
        if not results.get('next'):
            break
        results = spotify_client.next(results)
    return sources


def _extract_track(item):
    return item.get('track') or item


def clean_track_name(name):
    name = re.sub(r'[\(\[]\s*(?:feat\.?|ft\.?|with)\b.*?[\)\]]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[\(\[]\s*remix\b.*?[\)\]]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*[-–]\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|radio edit|acoustic)\b.*$', '', name, flags=re.IGNORECASE)
    return re.sub(r'\s{2,}', ' ', name).strip(' -–')


def _build_song_entry(item, lyrics_cache=None):
    track = _extract_track(item)
    if not track or not track.get('artists'):
        return None
    original_name = track.get('name', '')
    artist_name = track['artists'][0].get('name', '')
    album_images = track.get('album', {}).get('images', [])
    release_date = track.get('album', {}).get('release_date', '')
    try:
        release_year = int(release_date[:4])
    except (TypeError, ValueError):
        release_year = None
    lyrics = fetch_lrclib_lyrics(clean_track_name(original_name), artist_name, cache=lyrics_cache)
    has_real_lyrics = bool(lyrics)
    return Song(
        track_name=original_name,
        artist=artist_name,
        spotify_url=track.get('external_urls', {}).get('spotify', ''),
        lyrics=lyrics if has_real_lyrics else f'{original_name} {artist_name}',
        has_real_lyrics=has_real_lyrics,
        album_art_url=album_images[0].get('url') if album_images else None,
        spotify_uri=track.get('uri'),
        genres=tuple(track.get('_spotiword_genres', ())),
        release_year=release_year,
    ), is_hebrew(original_name) or is_hebrew(artist_name)


def enrich_track_metadata(spotify_client, items):
    """Attach optional artist genres to track items in batches."""
    artist_ids = {
        track['artists'][0].get('id')
        for item in items
        if (track := item.get('track'))
        and track.get('artists')
        and track['artists'][0].get('id')
    }
    genres_by_artist = {}
    try:
        artist_ids = list(artist_ids)
        for start in range(0, len(artist_ids), 50):
            response = spotify_client.artists(artist_ids[start:start + 50])
            for artist in response.get('artists', []):
                if artist and artist.get('id'):
                    genres_by_artist[artist['id']] = tuple(artist.get('genres', ()))
    except Exception:
        logging.exception('Spotify genre metadata could not be loaded; continuing without genres')
        return

    for item in items:
        track = _extract_track(item)
        artists = track.get('artists') or []
        artist_id = artists[0].get('id') if artists else None
        track['_spotiword_genres'] = genres_by_artist.get(artist_id, ())


def start_track_playback(spotify_client, spotify_uri):
    """Start a track on an available Spotify Connect device."""
    if not spotify_uri:
        raise RuntimeError("This track has no Spotify playback URI.")
    devices = spotify_client.devices().get('devices', [])
    usable_devices = [
        device for device in devices
        if device.get('id') and not device.get('is_restricted')
    ]
    if not usable_devices:
        raise RuntimeError("No Spotify device is available. Open Spotify and try again.")
    device = next((item for item in usable_devices if item.get('is_active')), usable_devices[0])
    try:
        spotify_client.start_playback(device_id=device.get('id'), uris=[spotify_uri])
    except SpotifyException as error:
        if error.http_status == 403:
            raise RuntimeError(
                "Spotify rejected playback. This feature requires a Spotify Premium account."
            ) from error
        if error.http_status == 404:
            raise RuntimeError(
                "Spotify could not find the selected device. Keep Spotify open and try again."
            ) from error
        raise RuntimeError(f"Spotify playback failed ({error.http_status}).") from error


def _catalog_queries(source):
    query_parts = []
    genre = source.get('genre')
    if genre:
        terms = GENRE_FILTERS.get(genre, (genre.casefold(),))
        query_parts.append(f"genre:{terms[0]}")
    decade = source.get('decade')
    if decade is not None:
        query_parts.append(f"year:{decade}-{decade + 9}")
    base_query = ' '.join(query_parts)
    if source.get('language') == 'Hebrew':
        # Spotify has no reliable language search filter. These metadata hints
        # improve recall before the exact Hebrew title/artist check below.
        seeds = ('עברית', 'ישראלי', 'מזרחית', 'מוזיקה', 'שיר', 'א', 'ה')
        return [f"{base_query} {seed}".strip() for seed in seeds]
    # Spotify requires a non-empty query. This broad fallback is used only
    # when the player chooses All genres and All years.
    return [base_query or 'a']


def _load_catalog_songs(
    spotify_client,
    source,
    max_songs,
    progress_callback=None,
    cancel_callback=None,
):
    """Build a final playable pool from Spotify catalog search results."""
    page_size = 10  # Spotify Search currently caps this endpoint at 10.
    search_plan = []
    for query in _catalog_queries(source):
        metadata = spotify_client.search(q=query, type='track', limit=1, offset=0)
        track_results = metadata.get('tracks', metadata)
        total_tracks = track_results.get('total', 0)
        total_pages = min(100, math.ceil(total_tracks / page_size))
        if total_pages:
            pages = random.sample(range(total_pages), min(20, total_pages))
            search_plan.extend((query, page) for page in pages)
    random.shuffle(search_plan)
    if not search_plan:
        return [], []

    language = source.get('language', 'English')
    seen_ids = set()
    playable = []
    lyrics_cache = LyricsCache()
    try:
        for query, page_number in search_plan[:100]:
            if cancel_callback and cancel_callback():
                raise LoadingCancelled()
            page = spotify_client.search(
                q=query,
                type='track',
                limit=page_size,
                offset=page_number * page_size,
            )
            candidates = []
            for item in page.get('tracks', {}).get('items', []):
                track = _extract_track(item)
                track_id = track.get('id') or track.get('uri')
                if not track_id or track_id in seen_ids:
                    continue
                seen_ids.add(track_id)
                artists = track.get('artists') or []
                artist_name = artists[0].get('name', '') if artists else ''
                text = f"{track.get('name', '')} {artist_name}"
                matches_language = is_hebrew(text) if language == 'Hebrew' else not is_hebrew(text)
                if matches_language:
                    candidates.append(item)

            if candidates:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [
                        executor.submit(_build_song_entry, item, lyrics_cache)
                        for item in candidates
                    ]
                    for future in as_completed(futures):
                        if cancel_callback and cancel_callback():
                            for pending in futures:
                                pending.cancel()
                            raise LoadingCancelled()
                        result = future.result()
                        if result and result[0].has_real_lyrics:
                            playable.append(result[0])
                            if progress_callback:
                                progress_callback(
                                    min(len(playable), max_songs),
                                    max_songs,
                                    f'Catalog playable songs: {min(len(playable), max_songs)}/{max_songs}',
                                )
                            if len(playable) >= max_songs:
                                break
                if len(playable) >= max_songs:
                    break
    finally:
        lyrics_cache.flush()

    if language == 'Hebrew':
        return [], playable[:max_songs]
    return playable[:max_songs], []


def load_and_categorize_songs(
    spotify_client,
    max_songs=100,
    progress_callback=None,
    cancel_callback=None,
    source=None,
):
    source = source or {'id': None, 'kind': 'liked', 'name': 'Liked Songs'}
    if source['kind'] == 'catalog':
        return _load_catalog_songs(
            spotify_client,
            source,
            max_songs,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
    else:
        page_size = 50 if source['kind'] == 'liked' else 100
        fetch_page = (
            spotify_client.current_user_saved_tracks
            if source['kind'] == 'liked'
            else lambda **kwargs: spotify_client.playlist_items(source['id'], **kwargs)
        )
        metadata = fetch_page(limit=1, offset=0)
        total_tracks = metadata.get('total', len(metadata.get('items', [])))
        total_pages = max(1, math.ceil(total_tracks / page_size))
        pages_needed = min(total_pages, max(1, math.ceil(max_songs / page_size) + 1))
        selected_pages = random.sample(range(total_pages), pages_needed)
        items = []
        for page_number in selected_pages:
            if cancel_callback and cancel_callback():
                raise LoadingCancelled()
            page = fetch_page(limit=page_size, offset=page_number * page_size)
            items.extend(page.get('items', []))

    unique_items = {}
    for item in items:
        track = _extract_track(item)
        unique_items[track.get('id') or f"{track.get('name')}::{track.get('uri')}"] = item
    selected_items = random.sample(list(unique_items.values()), min(max_songs, len(unique_items)))
    enrich_track_metadata(spotify_client, selected_items)
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
