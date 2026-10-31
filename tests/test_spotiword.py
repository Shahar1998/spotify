import pytest

from SpotiWord import (
    clean_track_name,
    create_spotify_client,
    get_lyric_snippet_clue,
    is_hebrew,
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
