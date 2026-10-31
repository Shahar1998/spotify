# SpotiWord

SpotiWord is a terminal-based lyric trivia game for songs saved in a user's Spotify library. It retrieves lyrics from LRCLIB, identifies signature words, creates multiple-choice rounds, and provides Spotify links for the songs.

Current version: **0.1.0**

## Requirements

- Python 3.8 or newer
- A Spotify Developer application
- Spotify credentials with permission to read the user's saved tracks

## Setup

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a local `.env` file based on `.env.example`:

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

Never commit `.env`, Spotify tokens, `.cache`, or personal library exports.

## Run

```powershell
python SpotiWord.py
```

To launch the GUI loading window:

```powershell
python gui_app.py
```

The GUI provides a responsive library-loading screen, selectable sample size, loading cancellation, language and difficulty setup, five-round gameplay, timer-based scoring, Spotify links, and a results dialog. Spotify and lyric loading run in the background so the window remains responsive. It uses a dark Spotify-inspired theme.

The first run may open a browser for Spotify authorization. Spotify authentication is created only when the application starts; importing the module does not trigger login.

## Test

Run the automated tests with:

```powershell
python -m pytest -q
```

The tests cover title cleanup, Hebrew detection, clue generation, word boundaries, scoring, decoy validation, configuration errors, and lyric caching. Tests do not call Spotify or LRCLIB over the network.

## Project layout

```text
SpotiWord.py          Main application and game flow
models.py             Typed Song data model
lyrics_client.py      LRCLIB access, retries, and local lyric cache
gui_app.py            PySide6 GUI loading window
tests/                Automated tests
SPECIFICATION.md      Product behavior and technical requirements
requirements.txt      Python dependencies
.env.example          Required environment variable template
```

The application uses typed `Song` objects rather than pandas DataFrames. Generated and private files such as `.venv/`, `.cache`, `.lyrics_cache.json`, `.env`, and `*.xlsx` are excluded from Git.

## Versioning

The project follows Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

The current development release is `0.1.0`. Git release tags use the `v` prefix, for example `v0.1.0`.
