import os
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import dotenv
import pandas as pd
from lyrics_client import fetch_lrclib_lyrics

__version__ = "0.1.0"

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
    name = re.sub(r'\(feat.*?\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\(ft.*?\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\(remix.*?\)', '', name, flags=re.IGNORECASE)
    return name.strip()


def tokenize_words(text):
    """Return lowercase alphabetic words, including contractions."""
    return re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*", text.lower(), re.UNICODE)


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
        for idx, lyrics in df['Lyrics'].items()
        if target_word not in set(tokenize_words(str(lyrics)))
    ]


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

def _build_song_entry(item):
    """Convert one Spotify saved-track item into a game song entry."""
    track = item.get('track')
    if not track or not track.get('artists'):
        return None

    original_name = track.get('name', '')
    artist_name = track['artists'][0].get('name', '')
    track_url = track.get('external_urls', {}).get('spotify', '')

    track_name_cleaned = clean_track_name(original_name)
    is_heb = is_hebrew(original_name) or is_hebrew(artist_name)

    lyrics_text = fetch_lrclib_lyrics(track_name_cleaned, artist_name)
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


def load_and_categorize_songs(spotify_client, max_songs=200):
    """Load a random sample of saved songs and retrieve their lyrics."""
    print("Loading your saved-song list from Spotify...")
    page_size = 50
    first_page = spotify_client.current_user_saved_tracks(limit=page_size, offset=0)
    total_tracks = first_page.get('total', len(first_page.get('items', [])))
    all_items = list(first_page.get('items', []))

    for offset in range(page_size, total_tracks, page_size):
        page = spotify_client.current_user_saved_tracks(
            limit=page_size,
            offset=offset,
        )
        all_items.extend(page.get('items', []))

    sample_size = min(max_songs, len(all_items))
    selected_items = random.sample(all_items, sample_size)
    print(f"Selected {sample_size} random tracks from {len(all_items)} saved songs.")
    print("Fetching lyrics (cached results are reused)...")

    english_songs = []
    hebrew_songs = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(_build_song_entry, selected_items)
        for number, result in enumerate(results, 1):
            print(f"\rFetching lyrics: {number}/{sample_size}", end='', flush=True)
            if not result:
                continue
            song_entry, is_heb = result
            if is_heb:
                hebrew_songs.append(song_entry)
            else:
                english_songs.append(song_entry)

    print()
    print(f"\n[Language Split Summary] English tracks: {len(english_songs)} | Hebrew tracks: {len(hebrew_songs)}\n")
    return pd.DataFrame(english_songs), pd.DataFrame(hebrew_songs)

def start_lyric_game(df, language_name, difficulty_level):
    if len(df) < 4:
        print(f"\nNot enough {language_name} songs found to start a game session (minimum 4 required).")
        return

    stop_words = {'the', 'a', 'an', 'and', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'you', 'i', 'me', 'my', 'it', 'is', 'chorus', 'verse', 'embedding', 'contributor', 'feat', 'oh', 'yeah', 'like', 'just', 'that', 'this', 'your'}
    
    word_to_tracks = {}
    for idx, row in df.iterrows():
        words = tokenize_words(row['Lyrics'])
        for w in set(words):
            if len(w) > 3 and w not in stop_words and any(c.isalpha() for c in w):
                if w not in word_to_tracks:
                    word_to_tracks[w] = []
                word_to_tracks[w].append(idx)

    valid_rounds_data = []
    real_lyrics_df = df[df['Has Real Lyrics'] == True]
    
    for idx, row in real_lyrics_df.iterrows():
        lyrics_text = row['Lyrics']
        title_words = set(tokenize_words(row['Track Name']))
        artist_words = set(tokenize_words(row['Artist']))
        excluded_words = stop_words.union(title_words).union(artist_words)
        
        words = tokenize_words(lyrics_text)
        filtered_words = [
            w for w in words 
            if len(w) > 3 and w not in excluded_words and any(c.isalpha() for c in w)
        ]
        
        if not filtered_words:
            continue
            
        word_counts = Counter(filtered_words)
        top_words = word_counts.most_common(5)
        
        if difficulty_level == 'easy' or len(top_words) == 1:
            target_word, freq = top_words[0]
        else:
            target_word, freq = random.choice(top_words[1:])
        
        indices = word_to_tracks.get(target_word, [])
        decoy_indices = get_decoy_indices(df, target_word)
        if 1 <= len(indices) <= 8 and len(decoy_indices) >= 3:
            if not any(item['target_word'] == target_word for item in valid_rounds_data):
                clue = get_lyric_snippet_clue(lyrics_text, target_word)
                valid_rounds_data.append({
                    'target_word': target_word,
                    'correct_idx': idx,
                    'clue': clue,
                    'decoy_indices': decoy_indices
                })

    if not valid_rounds_data:
        print(f"\nNo suitable signature words found in your {language_name} song pool.")
        return

    score = 0
    streak = 0
    total_rounds = min(5, len(valid_rounds_data))
    selected_rounds = random.sample(valid_rounds_data, total_rounds)

    print("\n" + "="*50)
    print(f"SpotiWord v{__version__}")
    print(f"🎯 WELCOME TO LYRIQ ({language_name.upper()} - {difficulty_level.upper()} MODE)! 🎯")
    print("="*50 + "\n")

    for round_num, round_info in enumerate(selected_rounds, 1):
        target_word = round_info['target_word']
        correct_idx = round_info['correct_idx']
        clue = round_info['clue']
        correct_track = df.loc[correct_idx]
        correct_dict = correct_track.to_dict()

        # These decoys were validated when the round was created.
        decoy_df = df.loc[round_info['decoy_indices']]
        decoys = decoy_df.sample(n=3)
        options = [correct_dict] + decoys.to_dict('records')
        random.shuffle(options)
        correct_option_num = options.index(correct_dict) + 1

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
    df_english, df_hebrew = load_and_categorize_songs(spotify_client, max_songs=200)
    
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
