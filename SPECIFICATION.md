# SpotiWord Specification

## 1. Product overview

SpotiWord is an interactive terminal trivia game based on a user's Spotify Liked Songs library. The game retrieves lyrics, identifies a signature word for a song, provides a lyric clue with the word hidden, and asks the player to select the matching song from four options.

Current release: `0.4.0`.

## 2. Technology and external services

- Python 3.8+
- `spotipy` for Spotify OAuth and saved-track access
- `requests` for HTTP communication
- `python-dotenv` for local configuration
- Dataclasses for typed song data and filtering
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
SpotiWord.py       Backward-compatible public entry point
core.py            Pure game rules, tokenization, and scoring
models.py          Typed `Song` data model shared by services and interfaces
spotify_service.py Spotify authentication and library loading
lyrics_client.py   LRCLIB requests, retries, response handling, and lyric caching
cli.py             Terminal interface
gui_app.py         PySide6 desktop interface and background library loading
tests/             Automated tests for pure and isolated behavior
```

Spotify authentication is created by `create_spotify_client()` when the application starts. Importing the module must not launch authentication or require a browser.

## 4. Data ingestion and language separation

1. Fetch up to `max_songs` saved tracks from Spotify.
2. Ignore unavailable or deleted Spotify tracks.
3. Preserve the original track name, primary artist, Spotify URL and URI, lyric text, and lyric availability flag.
4. Remove common feature and remix tags before querying LRCLIB.
5. Classify a track as Hebrew when its track name or primary artist contains Hebrew Unicode characters. All other tracks are placed in the English pool.

The loader first reads the total library size, samples random Spotify pages, deduplicates tracks, and then randomly selects up to the requested sample size. This avoids fetching every saved track solely to create a sample. Songs are represented as typed `Song` dataclasses throughout the application.

## 5. Lyric retrieval

LRCLIB is queried using the cleaned track name and primary artist.

The lyric client must:

- Use a request timeout.
- Retry temporary failures and rate limits.
- Treat unavailable lyrics as a normal condition.
- Cache successful lookups and confirmed not-found responses locally in the user's application-data directory.
- Do not cache temporary request failures or retryable HTTP errors as missing lyrics; log failed lookups so users can distinguish service problems from unavailable lyrics.
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

- Classic mode contains up to five valid rounds.
- Blitz mode starts with 60 seconds and presents valid rounds continuously until time expires.
- Fill in the Blank mode shows a song and a lyric line with one word hidden; players select the missing word from four options, with decoys drawn from other songs in the active pool.
- In Blitz mode, a correct answer adds four seconds and a wrong answer removes five seconds.
- Each round has one correct track and three validated decoys.
- Options are shuffled before display.
- The player selects an option from 1 through 4.
- Spotify URLs are displayed after each round.
- The GUI can optionally start the correct track on an available Spotify Connect device after an answer.
- Playback can be enabled automatically or started manually with **Play Correct Song**.
- Starting playback must not advance the current question.
- **Next Question** advances only when another valid round remains; **Finish Game** is used for the final valid round.
- Playback failures must be shown as friendly status messages and must not interrupt the game.
- Playback must explain when Spotify Premium or an available device is required.
- Blitz mode displays a live countdown bar that changes from green to amber to red.
- The GUI provides optional local sound cues for correct answers, wrong answers, streaks, and final countdown ticks.
- Sound feedback can be muted during gameplay.
- A correct-answer streak increases the score multiplier and is reported as an achievement at the end of the session.
- The 50/50 power-up removes two incorrect choices once per session.
- Blitz mode provides a one-use five-second time boost.
- Results display earned achievements such as three-answer streaks, five-answer streaks, and perfect runs.
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
- Release versions use Semantic Versioning and Git tags such as `v0.4.0`.

## 11. GUI requirements

The GUI must keep Spotify, LRCLIB, playback, and album-art network work off the main UI thread. While loading, it must display progress, support cancellation, and remain responsive. The current GUI provides Liked Songs and playlist selection, selectable sampling size, loading cancellation, language and difficulty setup, Classic, Blitz, and Fill in the Blank gameplay, timer-based scoring, combo streaks, power-ups, achievements, correct/wrong answer colors, optional Spotify Connect playback, clickable Spotify links, asynchronous album-art reveal, Hebrew RTL layout, local SQLite high-score history, a dark theme, sound feedback with mute control, and a results screen.

## 12. Planned improvements

- Improve random-page sampling when the selected pages contain too few unique tracks.
- Improve metadata cleaning for more release-tag formats.
- Separate Spotify access, analysis, and terminal presentation into additional modules.
- Add structured logging and a richer command-line interface.
- Improve language detection beyond track and artist metadata.
- Add code-signed Windows releases.
- Add automated CI builds and GitHub Release uploads.

## 13. v0.3 completed work

- First-run configuration assistance and packaged-app diagnostics.
- Random library sampling and playlist selection.

## 14. v0.4 completed work

- Fill in the Blank gameplay and mode-specific GUI routing.
- Avoid caching transient LRCLIB failures as unavailable lyrics, while retaining negative caching for confirmed not-found responses.
- Align application, installer, and documentation versions at `0.4.0`.
- Responsive PySide6 GUI and Windows installer pipeline.
