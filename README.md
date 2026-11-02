# SpotiWord

SpotiWord is a lyric trivia game with both terminal and desktop GUI modes. It uses songs saved in a user's Spotify library, retrieves lyrics from LRCLIB, identifies signature words, and creates multiple-choice rounds.

Current version: **0.4.0**

## Requirements

- Python 3.8 or newer
- A Spotify Developer application
- Spotify credentials with permission to read the user's saved tracks and control playback

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

The GUI provides a responsive loading screen with two source types: the user's library/playlists or the general Spotify Catalog. Language, genre, and release decade are selected once on the source screen, with **All genres** and **All years** available. Catalog games can be sampled by genre and decade. After loading, the user chooses only difficulty and game mode. The GUI also provides selectable sample size, loading cancellation, Classic five-round gameplay, Blitz 60-second gameplay, Fill in the Blank lyric rounds, a color-changing countdown bar, combo streak scoring, one-use power-ups, achievements, synthesized answer and streak sounds with a mute toggle, optional Spotify Connect playback after answers, timer-based scoring, answer-state colors, Spotify links, asynchronously loaded album artwork, RTL Hebrew support, local high-score history, and a results screen. Spotify and lyric loading run in the background so the window remains responsive. It uses a dark Spotify-inspired theme.

After answering, **Play Correct Song** starts the correct track without advancing the round. **Next Question** advances when more rounds are available; **Finish Game** appears on the final valid round.

The first GUI run provides a Spotify configuration dialog if credentials are missing. It may then open a browser for Spotify authorization. Playback control requires the `user-modify-playback-state` and `user-read-playback-state` scopes, a Spotify Premium account, and an available Spotify Connect device, so existing users may be asked to authorize SpotiWord again. Spotify authentication is created only when the application starts; importing the module does not trigger login. Runtime logs are stored in the user's SpotiWord application-data directory.

Library genre and decade filters operate on the sampled songs in the selected library or playlist. Catalog mode searches Spotify directly using the selected genre and decade, keeps searching random result pages, and retrieves lyrics until it reaches the requested playable-pool size or exhausts the searchable results. Hebrew Catalog mode uses several Hebrew metadata search hints before applying exact Hebrew title/artist detection. Genre metadata is optional because Spotify may return empty or deprecated artist-genre data; tracks without genre metadata remain available under **All genres**. A catalog search can still produce fewer playable songs when Spotify or LRCLIB returns too few matching tracks.

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

The tests cover title cleanup, Hebrew detection, clue generation, word boundaries, scoring, decoy validation, fill-in rounds and mode routing, configuration errors, lyric caching and retry behavior, GUI modes, power-ups, achievements, and playback device selection. Tests do not call Spotify or LRCLIB over the network.

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
build.ps1             PyInstaller build script
build-installer.ps1   Inno Setup build script
installer.iss         Windows installer definition
assets/               Application branding assets
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

The current version is `0.4.0`, which adds Fill in the Blank gameplay, improves LRCLIB failure handling, and adds library genre/decade filtering. Git release tags use the `v` prefix, for example `v0.4.0`.
