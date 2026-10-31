import json

import pytest
from models import Song
from lyrics_client import fetch_lrclib_lyrics

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
