# SpotiWord Specification

## 1. Product overview

SpotiWord is an interactive terminal trivia game based on a user's Spotify Liked Songs library. The game retrieves lyrics, identifies a signature word for a song, provides a lyric clue with the word hidden, and asks the player to select the matching song from four options.

Current release: `0.1.0` (development release).

## 2. Technology and external services

- Python 3.8+
- `spotipy` for Spotify OAuth and saved-track access
- `requests` for HTTP communication
- `python-dotenv` for local configuration
- `pandas` for song data and filtering
- `pytest` for automated tests
- `PySide6` for the desktop GUI
- LRCLIB for plain lyric retrieval

Required environment variables:

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
```

Secrets and OAuth tokens must remain local and must never be committed to Git.

## 3. Application architecture

```text
SpotiWord.py       Application orchestration, game flow, scoring, and word analysis
models.py          Typed `Song` data model shared by services and interfaces
lyrics_client.py   LRCLIB requests, retries, response handling, and lyric caching
gui_app.py         PySide6 desktop interface and background library loading
tests/             Automated tests for pure and isolated behavior
```

Spotify authentication is created by `create_spotify_client()` when the application starts. Importing the module must not launch authentication or require a browser.

## 4. Data ingestion and language separation

1. Fetch up to `max_songs` saved tracks from Spotify.
2. Ignore unavailable or deleted Spotify tracks.
3. Preserve the original track name, primary artist, Spotify URL, lyric text, and lyric availability flag.
4. Remove common feature and remix tags before querying LRCLIB.
5. Classify a track as Hebrew when its track name or primary artist contains Hebrew Unicode characters. All other tracks are placed in the English pool.

The loader first reads the total library size, samples random Spotify pages, deduplicates tracks, and then randomly selects up to the requested sample size. This avoids fetching every saved track solely to create a sample.

## 5. Lyric retrieval

LRCLIB is queried using the cleaned track name and primary artist.

The lyric client must:

- Use a request timeout.
- Retry temporary failures and rate limits.
- Treat unavailable lyrics as a normal condition.
- Cache successful and unavailable lookups locally in `.lyrics_cache.json`.
- Never allow a cache failure to stop the game.

Tracks without genuine lyrics may be displayed as options, but they must not generate signature words.

## 6. Word processing

Words are normalized using a shared Unicode-aware tokenizer. Matching is case-insensitive and must operate on complete words, not substrings. For example, `art` must not match `party`.

Signature-word rules:

- Ignore stop words, numbers, and words from the track title or artist name.
- A candidate word must contain alphabetic characters and be longer than three characters.
- Easy mode selects the most frequent candidate word.
- Hard mode selects randomly from the second through fifth most frequent candidates that exist.
- A candidate must occur in no more than eight tracks in the active language pool.
- A round is valid only when at least three decoy tracks do not contain the target word.
- The same target word must not create multiple rounds in one session.

## 7. Clue generation

The game searches lyric lines for the first line containing the target word. It replaces the complete target word with `____` and displays the resulting line as the clue.

If no suitable line is found, the game displays a generic hidden-word clue.

## 8. Gameplay

- A session contains up to five valid rounds.
- Each round has one correct track and three validated decoys.
- Options are shuffled before display.
- The player selects an option from 1 through 4.
- Spotify URLs are displayed after each round.
- If fewer than one valid round exists, the game exits with an informative message.

## 9. Scoring

For a correct answer:

```text
base points = 10
speed bonus = 15 when answered in 7 seconds or less
round score = (base points + speed bonus) * current streak
```

An incorrect answer gives zero points and resets the streak. Timing uses a monotonic clock so system clock changes do not affect the result.

## 10. Quality requirements

- Network failures must be handled without exposing credentials or crashing unexpectedly.
- Pure logic should be testable without Spotify or LRCLIB network access.
- New behavior should include automated tests.
- Private files must remain excluded by `.gitignore`.
- Release versions use Semantic Versioning and Git tags such as `v0.1.0`.

## 11. GUI requirements

The GUI must keep Spotify and LRCLIB work off the main UI thread. While loading, it must display progress, support cancellation, and remain responsive. The current GUI provides selectable sampling size, loading cancellation, language and difficulty setup, five-round gameplay, timer-based scoring, clickable Spotify links, a dark theme, and a results dialog while reusing the same game rules as the terminal version.

## 12. Planned improvements

- Improve random-page sampling when the selected pages contain too few unique tracks.
- Improve metadata cleaning for more release-tag formats.
- Separate Spotify access, analysis, and terminal presentation into additional modules.
- Add structured logging and a richer command-line interface.
- Improve language detection beyond track and artist metadata.
