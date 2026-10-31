# SpotiWord — Spotify Signature Word Trivia Game

**SpotiWord** is an interactive, terminal-based lyric trivia game that connects directly to a user's Spotify Liked Songs library. It extracts real song lyrics, isolates each track's defining "signature word" (excluding track titles and artist names), and challenges the player to identify which song features that word most prominently, complete with fill-in-the-blank line clues, streak multipliers, and direct playback links.

---

## 1. System Architecture & Tech Stack

* **Language:** Python 3.8+
* **Core Libraries:** 
  * `spotipy` — Spotify Web API wrapper for OAuth 2.0 authentication and library fetching (`user-library-read`).
  * `requests` — HTTP client for querying the keyless `lrclib.net` lyrics API.
  * `pandas` — Tabular data manipulation, language categorization, and filtering.
  * `collections.Counter` — Frequency analysis for signature word extraction.
  * `re` — Regular expressions for string cleaning, metadata sanitization, and language detection.
* **External APIs:**
  * **Spotify Web API:** Fetches saved tracks, artist metadata, and external web URLs.
  * **LRCLIB API (`https://lrclib.net/api/get`):** Retrieves plain text lyrics without requiring API keys or auth tokens.

---

## 2. Core Game Logic & Algorithms

### A. Data Ingestion & Language Separation
1. **Fetch Saved Tracks:** Queries `sp.current_user_saved_tracks(limit=max_songs)`.
2. **Sanitize Metadata:** Strips out noisy release tags (`(feat. ...)`, `(Remix)`, etc.) using regex to maximize lyrics API hit rates.
3. **Language Classification:** Uses Unicode character ranges (`[\u0590-\u05FF]`) to inspect track and artist names, separating the library into discrete **English** and **Hebrew** DataFrames to prevent cross-language mixing.

### B. Lyric Retrieval & Fallback Strategy
* Queries `lrclib.net/api/get` with `track_name` and `artist_name`.
* **Fallback Handling:** If a track's lyrics are unavailable (e.g., remixes, obscure tracks), the system assigns a fallback string (`track_name + artist_name`). A boolean flag (`Has Real Lyrics`) ensures only tracks with genuine lyric data are used for target word generation, while fallback tracks safely act as decoys.

### C. Signature Word Extraction Algorithm
To prevent giveaways, target words must follow strict constraints:
1. **Stop Word & Metadata Filtering:** Excludes common English stop words, numbers, and any words present in the track title or artist name.
2. **Frequency Analysis:** Uses `Counter` on the remaining lowercase tokens.
   * **Easy Mode:** Selects the #1 most frequent keyword.
   * **Hard Mode:** Randomly selects from the #2 to #5 most frequent keywords (deep cuts).
3. **Distribution Check:** Validates that the target word appears in **1 to 8 total tracks** in the active library pool to ensure enough valid decoy options exist.

### D. Fill-in-the-Blank Clue Generation
Scans the song's lyrics line by line to locate the first sentence containing the target word, replaces the target word with underscores (`____`), and displays it as a memory prompt (`Line Clue`).

---

## 3. Scoring & Gameplay Mechanics

* **Rounds:** 5 dynamic rounds per session.
* **Scoring Rules:**
  * **Base Points:** 10 points for a correct answer.
  * **Speed Bonus:** +15 points total if answered within $\le 7$ seconds.
  * **Streak Multiplier:** Score is multiplied by the current consecutive win streak (`Streak × Base Points`). Reset to 0 on incorrect answers.
* **Decoy Selection:** For each round, 3 random decoy tracks are sampled from the active pool, guaranteed *not* to contain the target word in their text.

---

## 4. Project File Structure

```text
spotify/
│
├── spotify.py           # Main game script & orchestration
├── requirements.txt     # Python dependencies (spotipy, requests, pandas, python-dotenv)
└── .env                 # Environment variables (Spotify API credentials)