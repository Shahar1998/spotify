import json

import pytest
import requests
from models import Song
from core import (
    HEBREW_STOP_WORDS,
    build_fillin_options,
    filter_songs,
    prepare_fillin_rounds,
    strip_hebrew_niqqud,
)
from lyrics_client import LyricsCache, fetch_lrclib_lyrics
from spotify_service import list_spotify_sources, start_track_playback

from SpotiWord import (
    clean_track_name,
    calculate_round_score,
    create_spotify_client,
    get_decoy_indices,
    get_lyric_snippet_clue,
    is_hebrew,
    build_round_options,
    prepare_game_rounds,
    tokenize_words,
)


def test_clean_track_name_removes_feature_and_remix_tags():
    assert clean_track_name("Song Title (feat. Guest Artist)") == "Song Title"
    assert clean_track_name("Song Title (Remix)") == "Song Title"
    assert clean_track_name("Song Title [feat. Guest Artist]") == "Song Title"
    assert clean_track_name("Song Title - 2011 Remaster") == "Song Title"


def test_hebrew_niqqud_is_removed_and_stop_words_exist():
    hebrew_with_marks = "\u05e9\u05b8\u05dc\u05d5\u05dd"

    assert strip_hebrew_niqqud(hebrew_with_marks) == "\u05e9\u05dc\u05d5\u05dd"
    assert "\u05e9\u05dc" in HEBREW_STOP_WORDS
    assert "\u05d0\u05e0\u05d9" in HEBREW_STOP_WORDS


def test_is_hebrew_detects_hebrew_text():
    assert is_hebrew("שלום עולם") is True
    assert is_hebrew("Hello world") is False


def test_get_lyric_snippet_clue_blanks_target_word():
    lyrics = "First line\nThis is the signature word in this line\nLast line"

    clue = get_lyric_snippet_clue(lyrics, "signature")

    assert clue == 'Line Clue: "This is the ____ word in this line"'


def test_word_matching_does_not_match_substrings():
    assert tokenize_words("party art") == ["party", "art"]

    clue = get_lyric_snippet_clue("The party starts\nThe art is here", "art")

    assert clue == 'Line Clue: "The ____ is here"'


def test_create_spotify_client_reports_missing_configuration(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    with pytest.raises(RuntimeError, match="Missing Spotify configuration"):
        create_spotify_client()


def test_calculate_round_score_applies_base_speed_and_streak():
    assert calculate_round_score(True, elapsed_time=8, streak=1) == 10
    assert calculate_round_score(True, elapsed_time=7, streak=1) == 25
    assert calculate_round_score(True, elapsed_time=3, streak=2) == 50


def test_calculate_round_score_returns_zero_for_incorrect_answers():
    assert calculate_round_score(False, elapsed_time=2, streak=4) == 0


def test_get_decoy_indices_guarantees_whole_word_exclusion():
    songs = [
        Song("Track 1", "Artist", "", "art art", True),
        Song("Track 2", "Artist", "", "party", True),
        Song("Track 3", "Artist", "", "music", True),
        Song("Track 4", "Artist", "", "artificial", True),
        Song("Track 5", "Artist", "", "dancing", True),
    ]

    assert get_decoy_indices(songs, "art") == [1, 2, 3, 4]


def test_tracks_without_real_lyrics_remain_safe_decoys():
    songs = [
        Song("Track 1", "Artist", "", "art art", True),
        Song("Track 2", "Artist", "", "fallback title", False),
        Song("Track 3", "Artist", "", "party", True),
        Song("Track 4", "Artist", "", "music", True),
    ]

    assert get_decoy_indices(songs, "art") == [1, 2, 3]


def test_prepare_game_rounds_and_options_are_playable():
    songs = [
        Song("Track One", "Artist A", "", "summer summer summer in the night", True),
        Song("Track Two", "Artist B", "", "ocean ocean ocean in the night", True),
        Song("Track Three", "Artist C", "", "mountain mountain mountain in the night", True),
        Song("Track Four", "Artist D", "", "forest forest forest in the night", True),
    ]

    rounds = prepare_game_rounds(songs, "easy", max_rounds=5)
    options, correct_option = build_round_options(songs, rounds[0])

    assert len(rounds) == 4
    assert len(options) == 4
    assert 1 <= correct_option <= 4


def test_prepare_fillin_rounds_create_four_word_options():
    songs = [
        Song("Track One", "Artist A", "", "summer summer summer in the night", True),
        Song("Track Two", "Artist B", "", "ocean ocean ocean in the night", True),
        Song("Track Three", "Artist C", "", "mountain mountain mountain in the night", True),
        Song("Track Four", "Artist D", "", "forest forest forest in the night", True),
    ]

    rounds = prepare_fillin_rounds(songs, "easy", max_rounds=5)

    assert len(rounds) == 4
    for round_info in rounds:
        options, correct_option = build_fillin_options(round_info)
        assert len(options) == 4
        assert options[correct_option - 1] == round_info["target_word"]
        assert "____" in round_info["blanked_line"]
        assert len(round_info["decoy_words"]) == 3


def test_fetch_lrclib_lyrics_caches_successful_response(tmp_path):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"plainLyrics": "Cached lyrics"}

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse()

    cache_path = tmp_path / "lyrics.json"
    session = FakeSession()

    first_result = fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache_path=cache_path
    )
    second_result = fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache_path=cache_path
    )

    assert first_result == "Cached lyrics"
    assert second_result == "Cached lyrics"
    assert session.calls == 1


def test_temporary_lyric_failure_is_retried_on_a_later_lookup(
    monkeypatch, tmp_path, caplog
):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"plainLyrics": "Lyrics recovered"}

    class FailOnceSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise requests.ConnectionError("temporary network failure")
            return FakeResponse()

    monkeypatch.setattr("lyrics_client.time.sleep", lambda _: None)
    session = FailOnceSession()
    cache = LyricsCache(tmp_path / "lyrics.json")

    first_result = fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache=cache, max_attempts=1
    )
    second_result = fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache=cache, max_attempts=1
    )

    assert first_result is None
    assert second_result == "Lyrics recovered"
    assert session.calls == 2
    assert "ConnectionError" in caplog.text


def test_retryable_http_failure_is_not_cached(monkeypatch, tmp_path, caplog):
    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            return {"plainLyrics": "Lyrics recovered"}

    class FailOnceSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse(503 if self.calls == 1 else 200)

    monkeypatch.setattr("lyrics_client.time.sleep", lambda _: None)
    session = FailOnceSession()
    cache = LyricsCache(tmp_path / "lyrics.json")

    assert fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache=cache, max_attempts=1
    ) is None
    assert fetch_lrclib_lyrics(
        "Song", "Artist", session=session, cache=cache, max_attempts=1
    ) == "Lyrics recovered"
    assert session.calls == 2
    assert "HTTP 503" in caplog.text


def test_not_found_lyrics_are_negative_cached(tmp_path):
    class NotFoundResponse:
        status_code = 404

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return NotFoundResponse()

    session = FakeSession()
    cache = LyricsCache(tmp_path / "lyrics.json")

    assert fetch_lrclib_lyrics("Song", "Artist", session=session, cache=cache) is None
    assert fetch_lrclib_lyrics("Song", "Artist", session=session, cache=cache) is None
    assert session.calls == 1


def test_expired_missing_lyrics_cache_is_retried(tmp_path):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"plainLyrics": "Lyrics are available now"}

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    cache_path = tmp_path / "lyrics.json"
    cache_path.write_text(
        json.dumps({"song::artist": {"lyrics": None, "cached_at": 0}}),
        encoding="utf-8",
    )

    result = fetch_lrclib_lyrics(
        "Song", "Artist", session=FakeSession(), cache_path=cache_path
    )

    assert result == "Lyrics are available now"


def test_lyrics_cache_flushes_and_reloads(tmp_path):
    cache_path = tmp_path / "lyrics.json"
    cache = LyricsCache(cache_path)
    cache.set("song::artist", "Lyrics in memory")

    assert cache.get("song::artist") == "Lyrics in memory"
    cache.flush()

    reloaded_cache = LyricsCache(cache_path)
    assert reloaded_cache.get("song::artist") == "Lyrics in memory"


def test_song_model_preserves_game_metadata():
    song = Song(
        track_name="Example",
        artist="Artist",
        spotify_url="https://open.spotify.com/track/example",
        lyrics="Example lyrics",
        has_real_lyrics=True,
        album_art_url="https://images.example/art.jpg",
    )

    record = song.to_record()

    assert record["Track Name"] == "Example"
    assert record["Album Art URL"].endswith("art.jpg")


def test_spotify_sources_include_liked_songs_and_playlists():
    class FakeSpotifyClient:
        def current_user_playlists(self, limit):
            return {
                "items": [{"id": "playlist-1", "name": "Road Trip"}],
                "next": None,
            }

    sources = list_spotify_sources(FakeSpotifyClient())

    assert sources[0] == {"id": None, "name": "Spotify Catalog", "kind": "catalog"}
    assert sources[1] == {"id": None, "name": "Liked Songs", "kind": "liked"}
    assert sources[2]["name"] == "Road Trip"


def test_catalog_source_searches_by_genre_and_decade(tmp_path, monkeypatch):
    class FakeSpotifyClient:
        def __init__(self):
            self.search_calls = []

        def search(self, **kwargs):
            self.search_calls.append(kwargs)
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 1, "items": []}}
            return {"tracks": {"items": []}}

    from spotify_service import load_and_categorize_songs

    client = FakeSpotifyClient()
    monkeypatch.setattr("spotify_service.enrich_track_metadata", lambda *args: None)
    load_and_categorize_songs(
        client,
        max_songs=20,
        source={"kind": "catalog", "genre": "Rock", "decade": 1990},
    )

    assert client.search_calls[0]["q"] == "genre:rock year:1990-1999"
    assert all(call["limit"] <= 10 for call in client.search_calls)


def test_hebrew_catalog_uses_multiple_language_search_hints():
    from spotify_service import _catalog_queries

    queries = _catalog_queries({"language": "Hebrew", "genre": None, "decade": None})

    assert "עברית" in queries[0]
    assert len(queries) >= 5


def test_catalog_fills_pool_across_pages_without_lyrics_or_duplicate_tracks(monkeypatch):
    from spotify_service import load_and_categorize_songs

    def track(track_id, name):
        return {
            "id": track_id,
            "name": name,
            "artists": [{"name": "Artist"}],
        }

    class FakeSpotifyClient:
        def __init__(self):
            self.page_offsets = []
            self.page_limits = []

        def search(self, **kwargs):
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 11}}
            self.page_offsets.append(kwargs["offset"])
            self.page_limits.append(kwargs["limit"])
            items = {
                0: [track("missing", "No Lyrics"), track("one", "First")],
                10: [track("one", "First"), track("two", "Second")],
            }
            return {"tracks": {"items": items.get(kwargs["offset"], [])}}

    built_ids = []

    def build_entry(item, cache):
        song = item.get("track") or item
        built_ids.append(song["id"])
        if song["id"] == "missing":
            return Song(song["name"], "Artist", "", "", False), False
        return Song(song["name"], "Artist", "", "real lyrics", True), False

    class FakeLyricsCache:
        def flush(self):
            pass

    monkeypatch.setattr("spotify_service._build_song_entry", build_entry)
    monkeypatch.setattr("spotify_service.LyricsCache", FakeLyricsCache)
    monkeypatch.setattr("spotify_service.random.shuffle", lambda pages: None)
    client = FakeSpotifyClient()

    english, hebrew = load_and_categorize_songs(
        client,
        max_songs=3,
        source={"kind": "catalog", "language": "English"},
    )

    assert [song.track_name for song in english] == ["First", "Second"]
    assert hebrew == []
    assert built_ids.count("one") == 1
    assert set(client.page_offsets) == {0, 10}
    assert client.page_limits == [10, 10]


def test_catalog_search_is_bounded_and_respects_spotify_offset_limit(monkeypatch):
    from spotify_service import load_and_categorize_songs

    class FakeSpotifyClient:
        def __init__(self):
            self.page_offsets = []

        def search(self, **kwargs):
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 10_000}}
            offset = kwargs["offset"]
            self.page_offsets.append(offset)
            return {"tracks": {"items": []}}

    class FakeLyricsCache:
        def flush(self):
            pass

    monkeypatch.setattr("spotify_service.LyricsCache", FakeLyricsCache)
    monkeypatch.setattr("spotify_service.random.shuffle", lambda pages: None)
    client = FakeSpotifyClient()

    load_and_categorize_songs(
        client,
        max_songs=100,
        source={"kind": "catalog", "language": "English"},
    )

    assert len(client.page_offsets) == 20
    assert all(offset <= 1000 for offset in client.page_offsets)
    assert len(set(client.page_offsets)) == 20


def test_hebrew_catalog_sample_is_shared_across_search_hints(monkeypatch):
    from spotify_service import _catalog_queries, load_and_categorize_songs

    class FakeSpotifyClient:
        def __init__(self):
            self.page_queries = []

        def search(self, **kwargs):
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 500}}
            self.page_queries.append(kwargs["q"])
            return {"tracks": {"items": []}}

    class FakeLyricsCache:
        def flush(self):
            pass

    monkeypatch.setattr("spotify_service.LyricsCache", FakeLyricsCache)
    monkeypatch.setattr("spotify_service.random.shuffle", lambda pages: None)
    client = FakeSpotifyClient()
    queries = _catalog_queries({"language": "Hebrew"})

    load_and_categorize_songs(
        client,
        max_songs=100,
        source={"kind": "catalog", "language": "Hebrew"},
    )

    assert len(client.page_queries) == 20
    assert set(client.page_queries) == set(queries[:20])


def test_catalog_cancellation_stops_before_next_page(monkeypatch):
    from spotify_service import LoadingCancelled, load_and_categorize_songs

    class FakeSpotifyClient:
        def __init__(self):
            self.page_offsets = []

        def search(self, **kwargs):
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 11}}
            self.page_offsets.append(kwargs["offset"])
            return {"tracks": {"items": []}}

    class FakeLyricsCache:
        def flush(self):
            pass

    monkeypatch.setattr("spotify_service.random.shuffle", lambda pages: None)
    monkeypatch.setattr("spotify_service.LyricsCache", FakeLyricsCache)
    client = FakeSpotifyClient()

    with pytest.raises(LoadingCancelled):
        load_and_categorize_songs(
            client,
            max_songs=1,
            cancel_callback=lambda: len(client.page_offsets) >= 1,
            source={"kind": "catalog", "language": "English"},
        )

    assert client.page_offsets == [0]


@pytest.mark.parametrize(
    ("language", "track_name"),
    [("English", "English Song"), ("Hebrew", "שיר בעברית")],
)
def test_catalog_filters_tracks_for_selected_language(
    language, track_name, monkeypatch
):
    from spotify_service import load_and_categorize_songs

    class FakeSpotifyClient:
        def search(self, **kwargs):
            if kwargs["limit"] == 1:
                return {"tracks": {"total": 1}}
            return {"tracks": {"items": [{
                "id": "selected-language",
                "name": track_name,
                "artists": [{"name": "Artist"}],
            }]}}

    class FakeLyricsCache:
        def flush(self):
            pass

    monkeypatch.setattr(
        "spotify_service._build_song_entry",
        lambda item, cache: (
            Song(track_name, "Artist", "", "lyrics", True),
            language == "Hebrew",
        ),
    )
    monkeypatch.setattr("spotify_service.LyricsCache", FakeLyricsCache)
    monkeypatch.setattr("spotify_service.random.shuffle", lambda pages: None)

    english, hebrew = load_and_categorize_songs(
        FakeSpotifyClient(),
        max_songs=1,
        source={"kind": "catalog", "language": language},
    )

    assert len(english) == (language == "English")
    assert len(hebrew) == (language == "Hebrew")


def test_start_track_playback_targets_active_device():
    class FakeSpotifyClient:
        def __init__(self):
            self.started = None

        def devices(self):
            return {"devices": [
                {"id": "inactive", "is_active": False, "is_restricted": False},
                {"id": "active", "is_active": True, "is_restricted": False},
            ]}

        def start_playback(self, **kwargs):
            self.started = kwargs

    client = FakeSpotifyClient()
    start_track_playback(client, "spotify:track:example")

    assert client.started == {
        "device_id": "active",
        "uris": ["spotify:track:example"],
    }


def test_filter_songs_supports_genre_and_decade():
    songs = [
        Song("Rock 90s", "Band", "", "lyrics", True, genres=("album rock",), release_year=1995),
        Song("Rock 00s", "Band", "", "lyrics", True, genres=("album rock",), release_year=2005),
        Song("Pop 90s", "Singer", "", "lyrics", True, genres=("dance pop",), release_year=1995),
    ]

    filtered = filter_songs(songs, genre="Rock", decade=1990)

    assert [song.track_name for song in filtered] == ["Rock 90s"]
