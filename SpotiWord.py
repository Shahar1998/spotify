import os
import random
import re
import time
import math
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import dotenv
import pandas as pd
from lyrics_client import LyricsCache, fetch_lrclib_lyrics

__version__ = "0.1.0"

STOP_WORDS = {
    'the', 'a', 'an', 'and', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'you', 'i', 'me', 'my', 'it', 'is', 'chorus', 'verse', 'embedding',
    'contributor', 'feat', 'oh', 'yeah', 'like', 'just', 'that', 'this',
    'your'
}


class LoadingCancelled(Exception):
    """Raised when the user cancels library loading."""

dotenv.load_dotenv()

def create_spotify_client():
    """Create an authenticated Spotify client from the local environment."""
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIFY_REDIRECT_URI')

    missing_values = []
    if not client_id:
        missing_values.append('SPOTIFY_CLIENT_ID')
    if not client_secret:
        missing_values.append('SPOTIFY_CLIENT_SECRET')
    if not redirect_uri:
        missing_values.append('SPOTIFY_REDIRECT_URI')

    if missing_values:
        missing = ', '.join(missing_values)
        raise RuntimeError(f'Missing Spotify configuration: {missing}')

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope='user-library-read'
    )
    return spotipy.Spotify(auth_manager=auth_manager)

def clean_track_name(name):
    """Removes extra tags like '(feat. ...)', 'Remix', etc. to help match lyrics accurately."""
    name = re.sub(
        r'[\(\[]\s*(?:feat\.?|ft\.?|with)\b.*?[\)\]]',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(
        r'[\(\[]\s*remix\b.*?[\)\]]',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(
        r'\s*[-–]\s*(?:\d{4}\s+)?(?:remaster(?:ed)?|live|radio edit|acoustic)\b.*$',
        '', name, flags=re.IGNORECASE
    )
    return re.sub(r'\s{2,}', ' ', name).strip(' -–')


def strip_hebrew_niqqud(text):
    """Remove Hebrew cantillation marks and vowel points."""
    return re.sub(r'[\u0591-\u05C7]', '', text)


HEBREW_STOP_WORDS = {
    'של', 'את', 'זה', 'על', 'עם', 'לא', 'כי', 'אם', 'אני', 'אתה', 'הוא',
    'היא', 'אנחנו', 'הם', 'הן', 'מה', 'מי', 'כל', 'רק', 'עוד', 'שלי',
    'שלך', 'לו', 'לה', 'אותי', 'אותך', 'אותו', 'אותה', 'אותנו', 'היה',
    'היו', 'תהיה', 'יהיה', 'כבר', 'שם', 'פה', 'כמו', 'אבל', 'טוב'
}


def get_stop_words(text):
    stop_words = set(STOP_WORDS)
    if is_hebrew(text):
        stop_words.update(HEBREW_STOP_WORDS)
    return stop_words


def tokenize_words(text):
    """Return lowercase alphabetic words, including contractions."""
    normalized_text = strip_hebrew_niqqud(text).lower()
    return re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*", normalized_text, re.UNICODE)


def calculate_round_score(is_correct, elapsed_time, streak):
    """Calculate round points using the specification's scoring rules."""
    if not is_correct:
        return 0

    base_points = 10
    speed_bonus = 15 if elapsed_time <= 7 else 0
    return (base_points + speed_bonus) * streak


def get_decoy_indices(df, target_word):
    """Return track indices whose lyrics do not contain the target word."""
    return [
        idx
        for idx, row in df.iterrows()
        if not row.get('Has Real Lyrics', True)
        or target_word not in set(tokenize_words(str(row['Lyrics'])))
    ]


def prepare_game_rounds(df, difficulty_level, max_rounds=5):
    """Create playable rounds using the same rules for CLI and GUI games."""
    word_to_tracks = {}
    for idx, row in df.iterrows():
        if not row['Has Real Lyrics']:
            continue
        stop_words = get_stop_words(row['Lyrics'])
        words = tokenize_words(row['Lyrics'])
        for word in set(words):
            if len(word) > 3 and word not in stop_words and any(c.isalpha() for c in word):
                word_to_tracks.setdefault(word, []).append(idx)

    valid_rounds = []
    real_lyrics_df = df[df['Has Real Lyrics'] == True]
    for idx, row in real_lyrics_df.iterrows():
        title_words = set(tokenize_words(row['Track Name']))
        artist_words = set(tokenize_words(row['Artist']))
        excluded_words = get_stop_words(row['Lyrics']).union(title_words).union(artist_words)
        filtered_words = [
            word for word in tokenize_words(row['Lyrics'])
            if len(word) > 3
            and word not in excluded_words
            and any(c.isalpha() for c in word)
        ]
        if not filtered_words:
            continue

        top_words = Counter(filtered_words).most_common(5)
        if difficulty_level == 'easy' or len(top_words) == 1:
            target_word = top_words[0][0]
        else:
            target_word = random.choice(top_words[1:])[0]

        decoy_indices = get_decoy_indices(df, target_word)
        if (
            1 <= len(word_to_tracks.get(target_word, [])) <= 8
            and len(decoy_indices) >= 3
            and not any(item['target_word'] == target_word for item in valid_rounds)
        ):
            valid_rounds.append({
                'target_word': target_word,
                'correct_idx': idx,
                'clue': get_lyric_snippet_clue(row['Lyrics'], target_word),
                'decoy_indices': decoy_indices,
            })

    return random.sample(valid_rounds, min(max_rounds, len(valid_rounds)))


def build_round_options(df, round_info):
    """Build shuffled answer options and return the correct option index."""
    correct_dict = df.loc[round_info['correct_idx']].to_dict()
    decoy_df = df.loc[round_info['decoy_indices']]
    options = [correct_dict] + decoy_df.sample(n=3).to_dict('records')
    random.shuffle(options)
    return options, options.index(correct_dict) + 1


def is_hebrew(text):
    """Detects if a string contains Hebrew characters."""
    return bool(re.search(r'[\u0590-\u05FF]', text))

def get_lyric_snippet_clue(lyrics_text, target_word):
    """Finds a single line of lyrics containing the target word and blanks it out."""
    lines = lyrics_text.split('\n')
    pattern = re.compile(
        rf"(?<!\w){re.escape(target_word)}(?!\w)",
        re.IGNORECASE
    )
    
    for line in lines:
        cleaned_line = line.strip()
        if pattern.search(cleaned_line) and len(cleaned_line) > 10:
            blanked_line = pattern.sub("____", cleaned_line)
            return f"Line Clue: \"{blanked_line}\""
            
    return f"Line Clue: Contains the word '____'"

def _build_song_entry(item, lyrics_cache=None):
    """Convert one Spotify saved-track item into a game song entry."""
    track = item.get('track')
    if not track or not track.get('artists'):
        return None

    original_name = track.get('name', '')
    artist_name = track['artists'][0].get('name', '')
    track_url = track.get('external_urls', {}).get('spotify', '')

    track_name_cleaned = clean_track_name(original_name)
    is_heb = is_hebrew(original_name) or is_hebrew(artist_name)

    lyrics_text = fetch_lrclib_lyrics(
        track_name_cleaned,
        artist_name,
        cache=lyrics_cache,
    )
    has_real_lyrics = bool(lyrics_text)

    if not has_real_lyrics:
        lyrics_text = f"{original_name} {artist_name}"

    return {
        'Track Name': original_name,
        'Artist': artist_name,
        'Spotify URL': track_url,
        'Lyrics': lyrics_text,
        'Has Real Lyrics': has_real_lyrics
    }, is_heb


def load_and_categorize_songs(
    spotify_client,
    max_songs=100,
    progress_callback=None,
    cancel_callback=None,
):
    """Load random Spotify pages and retrieve lyrics for the sample."""
    print("Loading random pages from your Spotify library...")
    page_size = 50
    metadata = spotify_client.current_user_saved_tracks(limit=1, offset=0)
    total_tracks = metadata.get('total', len(metadata.get('items', [])))
    total_pages = max(1, math.ceil(total_tracks / page_size))
    pages_needed = min(total_pages, max(1, math.ceil(max_songs / page_size) + 1))
    selected_pages = random.sample(range(total_pages), pages_needed)
    all_items = []

    for page_number in selected_pages:
        if cancel_callback and cancel_callback():
            raise LoadingCancelled()
        page = spotify_client.current_user_saved_tracks(
            limit=page_size,
            offset=page_number * page_size,
        )
        all_items.extend(page.get('items', []))

    unique_items = {}
    for item in all_items:
        track = item.get('track') or {}
        track_id = track.get('id') or f"{track.get('name')}::{track.get('uri')}"
        unique_items[track_id] = item
    all_items = list(unique_items.values())
    sample_size = min(max_songs, len(all_items))
    selected_items = random.sample(all_items, sample_size)
    print(f"Selected {sample_size} random tracks from {len(all_items)} saved songs.")
    print("Fetching lyrics (cached results are reused)...")
    if progress_callback:
        progress_callback(0, sample_size, f"Selected {sample_size} random tracks")

    english_songs = []
    hebrew_songs = []

    lyrics_cache = LyricsCache()
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(_build_song_entry, item, lyrics_cache)
            for item in selected_items
        ]
        for number, future in enumerate(as_completed(futures), 1):
            if cancel_callback and cancel_callback():
                for pending_future in futures:
                    pending_future.cancel()
                raise LoadingCancelled()
            result = future.result()
            print(f"\rFetching lyrics: {number}/{sample_size}", end='', flush=True)
            if progress_callback:
                progress_callback(number, sample_size, f"Fetching lyrics: {number}/{sample_size}")
            if not result:
                continue
            song_entry, is_heb = result
            if is_heb:
                hebrew_songs.append(song_entry)
            else:
                english_songs.append(song_entry)

    lyrics_cache.flush()
    print()
    print(f"\n[Language Split Summary] English tracks: {len(english_songs)} | Hebrew tracks: {len(hebrew_songs)}\n")
    return pd.DataFrame(english_songs), pd.DataFrame(hebrew_songs)

def start_lyric_game(df, language_name, difficulty_level):
    if len(df) < 4:
        print(f"\nNot enough {language_name} songs found to start a game session (minimum 4 required).")
        return

    selected_rounds = prepare_game_rounds(df, difficulty_level)
    if not selected_rounds:
        print(f"\nNo suitable signature words found in your {language_name} song pool.")
        return

    score = 0
    streak = 0
    total_rounds = len(selected_rounds)

    print("\n" + "="*50)
    print(f"SpotiWord v{__version__}")
    print(f"🎯 WELCOME TO LYRIQ ({language_name.upper()} - {difficulty_level.upper()} MODE)! 🎯")
    print("="*50 + "\n")

    for round_num, round_info in enumerate(selected_rounds, 1):
        target_word = round_info['target_word']
        clue = round_info['clue']
        options, correct_option_num = build_round_options(df, round_info)
        correct_track = df.loc[round_info['correct_idx']]

        print(f"\n--- Round {round_num} of {total_rounds} | Current Score: {score} | Streak: {streak} 🔥 ---")
        print(f"Signature Word: **\"{target_word.upper()}\"**")
        print(f"💡 {clue}\n")
        
        print("Which of these 4 songs features this word?")
        for i, opt in enumerate(options, 1):
            print(f"  [{i}] {opt['Track Name']} — {opt['Artist']}")

        start_time = time.monotonic()
        
        while True:
            try:
                guess = int(input("\nYour choice (1-4): "))
                if 1 <= guess <= 4:
                    break
            except ValueError:
                pass
            print("Please enter a valid number between 1 and 4.")

        elapsed_time = time.monotonic() - start_time

        if guess == correct_option_num:
            streak += 1
            points_gained = calculate_round_score(True, elapsed_time, streak)
            score += points_gained
            print(f"🎉 Correct! (+{points_gained} pts) Answered in {round(elapsed_time, 1)}s!")
        else:
            streak = 0
            print(f"❌ Wrong! The correct answer was Option [{correct_option_num}]: '{correct_track['Track Name']}'")

        print("\n🎧 Listen to the full tracks on Spotify:")
        for i, opt in enumerate(options, 1):
            print(f"  [{i}] {opt['Track Name']}: {opt['Spotify URL']}")

    print("\n" + "="*50)
    print(f"🏆 GAME OVER! Final Score: {score}")
    print("="*50)

if __name__ == '__main__':
    spotify_client = create_spotify_client()
    df_english, df_hebrew = load_and_categorize_songs(spotify_client, max_songs=100)
    
    print("Select Game Language:")
    print("  [1] English Songs")
    print("  [2] Hebrew Songs")
    
    lang_choice = input("\nEnter choice (1 or 2): ").strip()
    selected_df = df_hebrew if lang_choice == '2' else df_english
    selected_lang = "Hebrew" if lang_choice == '2' else "English"

    print("\nSelect Difficulty Tier:")
    print("  [1] Easy (Top Signature Word)")
    print("  [2] Hard (Lyrical Deep-Cuts)")
    
    diff_choice = input("\nEnter choice (1 or 2): ").strip()
    selected_diff = "hard" if diff_choice == '2' else "easy"

    start_lyric_game(selected_df, selected_lang, selected_diff)
