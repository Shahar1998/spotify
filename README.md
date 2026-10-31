# SpotiWord

SpotiWord is a terminal-based lyric trivia game for songs saved in a user's Spotify library. It retrieves lyrics from LRCLIB, identifies signature words, creates multiple-choice rounds, and provides Spotify links for the songs.

Current version: **0.3.0**

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

Never commit `.env`, Spotify tokens, `.cache`, or personal library exports. The packaged application reads `.env` beside the executable, while OAuth and lyric caches are stored in the user's application-data directory.

## Run

```powershell
python SpotiWord.py
```

The terminal implementation can also be started explicitly with:

```powershell
python cli.py
```

To launch the GUI loading window:

```powershell
python gui_app.py
```

The GUI provides a responsive library-loading screen, Liked Songs and playlist selection, selectable sample size, loading cancellation, language and difficulty setup, Classic five-round gameplay, Blitz 60-second gameplay, a color-changing countdown bar, combo streak scoring, one-use power-ups, achievements, synthesized answer and streak sounds with a mute toggle, timer-based scoring, answer-state colors, Spotify links, asynchronously loaded album artwork, RTL Hebrew support, local high-score history, and a results screen. Spotify and lyric loading run in the background so the window remains responsive. It uses a dark Spotify-inspired theme.

The first GUI run provides a Spotify configuration dialog if credentials are missing. It may then open a browser for Spotify authorization. Spotify authentication is created only when the application starts; importing the module does not trigger login. Runtime logs are stored in the user's SpotiWord application-data directory.

## Test

Run the automated tests with:

```powershell
python -m pytest -q
```

## Build a Windows executable

Install the project dependencies, then run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\build.ps1
```

The executable is created at `dist\SpotiWord\SpotiWord.exe`. Keep the `.env` file beside the executable; credentials are not bundled into the application.

To build an installer, install Inno Setup and run:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\build-installer.ps1
```

The installer is created in the `installer/` directory. It installs shortcuts and includes `.env.example`, never the real `.env` file.

The tests cover title cleanup, Hebrew detection, clue generation, word boundaries, scoring, decoy validation, configuration errors, and lyric caching. Tests do not call Spotify or LRCLIB over the network.

## Project layout

```text
SpotiWord.py          Backward-compatible public entry point
core.py               Pure game rules, tokenization, and scoring
models.py             Typed Song data model
spotify_service.py    Spotify authentication and library loading
lyrics_client.py      LRCLIB access, retries, and local lyric cache
scores.py             Local SQLite high-score history
cli.py                Terminal interface
gui_app.py            PySide6 desktop interface
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

The current release is `0.3.0`. Git release tags use the `v` prefix, for example `v0.3.0`.
