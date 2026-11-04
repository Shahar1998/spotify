import random
import re
from collections import Counter

from models import Song


__version__ = "0.4.0"

GENRE_FILTERS = {
    'Rock': ('rock',),
    'Pop': ('pop',),
    'Hip-Hop': ('hip hop', 'hip-hop', 'rap'),
    'R&B': ('r&b', 'soul', 'funk'),
    'Electronic': ('electronic', 'house', 'techno', ' edm'),
    'Jazz': ('jazz',),
    'Classical': ('classical', 'orchestral'),
    'Metal': ('metal',),
    'Country': ('country',),
    'Reggae': ('reggae',),
    'Indie': ('indie',),
    'Alternative': ('alternative',),
}

STOP_WORDS = {
    'the', 'a', 'an', 'and', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'you', 'i', 'me', 'my', 'it', 'is', 'chorus', 'verse', 'embedding',
    'contributor', 'feat', 'oh', 'yeah', 'like', 'just', 'that', 'this',
    'your'
}

HEBREW_STOP_WORDS = {
    'של', 'את', 'זה', 'על', 'עם', 'לא', 'כי', 'אם', 'אני', 'אתה', 'הוא',
    'היא', 'אנחנו', 'הם', 'הן', 'מה', 'מי', 'כל', 'רק', 'עוד', 'שלי',
    'שלך', 'לו', 'לה', 'אותי', 'אותך', 'אותו', 'אותה', 'אותנו', 'היה',
    'היו', 'תהיה', 'יהיה', 'כבר', 'שם', 'פה', 'כמו', 'אבל', 'טוב'
}


def is_hebrew(text):
    return bool(re.search(r'[\u0590-\u05FF]', text))


def is_arabic(text):
    return bool(
        re.search(
            r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]',
            text,
        )
    )


def strip_hebrew_niqqud(text):
    return re.sub(r'[\u0591-\u05C7]', '', text)


def get_stop_words(text):
    stop_words = set(STOP_WORDS)
    if is_hebrew(text):
        stop_words.update(HEBREW_STOP_WORDS)
    return stop_words


def tokenize_words(text):
    normalized_text = strip_hebrew_niqqud(text).lower()
    return re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)*", normalized_text, re.UNICODE)


def calculate_round_score(is_correct, elapsed_time, streak):
    if not is_correct:
        return 0
    base_points = 10
    speed_bonus = 15 if elapsed_time <= 7 else 0
    return (base_points + speed_bonus) * streak


def get_lyric_snippet_clue(lyrics_text, target_word):
    normalized_lyrics = strip_hebrew_niqqud(lyrics_text)
    lines = normalized_lyrics.split('\n')
    pattern = re.compile(
        rf"(?<!\w){re.escape(strip_hebrew_niqqud(target_word))}(?!\w)",
        re.IGNORECASE,
    )
    for line in lines:
        cleaned_line = line.strip()
        if pattern.search(cleaned_line):
            return f'Line Clue: "{cleaned_line}"'
    return f"Line Clue: Contains the word '{target_word}'"


def get_decoy_indices(songs, target_word):
    return [
        index
        for index, song in enumerate(songs)
        if not song.has_real_lyrics
        or target_word not in set(tokenize_words(song.lyrics))
    ]


def prepare_game_rounds(songs, difficulty_level, max_rounds=5):
    word_to_tracks = {}
    for index, song in enumerate(songs):
        if not song.has_real_lyrics:
            continue
        stop_words = get_stop_words(song.lyrics)
        for word in set(tokenize_words(song.lyrics)):
            if len(word) > 3 and word not in stop_words and any(c.isalpha() for c in word):
                word_to_tracks.setdefault(word, []).append(index)

    valid_rounds = []
    for index, song in enumerate(songs):
        if not song.has_real_lyrics:
            continue
        title_words = set(tokenize_words(song.track_name))
        artist_words = set(tokenize_words(song.artist))
        excluded_words = get_stop_words(song.lyrics).union(title_words).union(artist_words)
        filtered_words = [
            word for word in tokenize_words(song.lyrics)
            if len(word) > 3 and word not in excluded_words and any(c.isalpha() for c in word)
        ]
        if not filtered_words:
            continue

        top_words = Counter(filtered_words).most_common(5)
        target_word = top_words[0][0] if difficulty_level == 'easy' or len(top_words) == 1 else random.choice(top_words[1:])[0]
        decoy_indices = get_decoy_indices(songs, target_word)
        if (
            1 <= len(word_to_tracks.get(target_word, [])) <= 8
            and len(decoy_indices) >= 3
            and not any(item['target_word'] == target_word for item in valid_rounds)
        ):
            valid_rounds.append({
                'target_word': target_word,
                'correct_idx': index,
                'clue': get_lyric_snippet_clue(song.lyrics, target_word),
                'decoy_indices': decoy_indices,
            })

    return random.sample(valid_rounds, min(max_rounds, len(valid_rounds)))


def filter_songs(songs, genre=None, decade=None):
    """Filter songs by broad genre and release decade without requiring metadata."""
    genre_terms = GENRE_FILTERS.get(genre, ()) if genre else ()
    filtered = []
    for song in songs:
        if genre_terms:
            normalized_genres = [item.casefold() for item in song.genres]
            if not any(
                term in current_genre
                for term in genre_terms
                for current_genre in normalized_genres
            ):
                continue
        if decade:
            if song.release_year is None or song.release_year // 10 * 10 != decade:
                continue
        filtered.append(song)
    return filtered


def prepare_fillin_rounds(songs, difficulty_level, max_rounds=5):
    """Create fill-in-the-blank rounds: guess the missing word from a lyric line.

    Each round shows the song name and artist, a lyric line with one word
    blanked out, and four word choices (one correct, three decoys drawn
    from the lyrics of other songs in the pool).
    """
    all_words_by_song = {}
    for index, song in enumerate(songs):
        if not song.has_real_lyrics:
            continue
        title_words = set(tokenize_words(song.track_name))
        artist_words = set(tokenize_words(song.artist))
        stop = get_stop_words(song.lyrics).union(title_words).union(artist_words)
        words = [
            w for w in tokenize_words(song.lyrics)
            if len(w) > 3 and w not in stop and any(c.isalpha() for c in w)
        ]
        if words:
            all_words_by_song[index] = words

    valid_rounds = []
    used_words = set()

    song_indices = list(all_words_by_song.keys())
    random.shuffle(song_indices)

    for index in song_indices:
        if len(valid_rounds) >= max_rounds:
            break
        song = songs[index]
        words = all_words_by_song[index]
        word_counts = Counter(words)

        # Pick the target word based on difficulty.
        candidates = word_counts.most_common(5)
        if not candidates:
            continue
        if difficulty_level == 'easy' or len(candidates) == 1:
            target_word = candidates[0][0]
        else:
            target_word = random.choice(candidates[1:])[0]

        if target_word in used_words:
            continue

        # Find a lyric line containing the target word.
        normalized_lyrics = strip_hebrew_niqqud(song.lyrics)
        lines = normalized_lyrics.split('\n')
        pattern = re.compile(
            rf"(?<!\w){re.escape(strip_hebrew_niqqud(target_word))}(?!\w)",
            re.IGNORECASE,
        )
        blanked_line = None
        for line in lines:
            cleaned = line.strip()
            if pattern.search(cleaned) and len(cleaned) > 10:
                blanked_line = pattern.sub("____", cleaned)
                break

        if not blanked_line:
            continue

        # Build 3 decoy words from lyrics of OTHER songs.
        decoy_pool = set()
        for other_index, other_words in all_words_by_song.items():
            if other_index == index:
                continue
            for w in other_words:
                if w != target_word and len(w) > 3:
                    decoy_pool.add(w)

        if len(decoy_pool) < 3:
            continue

        decoy_words = random.sample(sorted(decoy_pool), 3)
        used_words.add(target_word)

        valid_rounds.append({
            'song_index': index,
            'target_word': target_word,
            'blanked_line': blanked_line,
            'decoy_words': decoy_words,
        })

    return valid_rounds


def build_fillin_options(round_info):
    """Build shuffled word options for a fill-in round. Returns (options, correct_index_1based)."""
    correct = round_info['target_word']
    options = [correct] + round_info['decoy_words']
    random.shuffle(options)
    return options, options.index(correct) + 1


def build_round_options(songs, round_info):
    correct_song = songs[round_info['correct_idx']]
    decoys = [songs[index] for index in random.sample(round_info['decoy_indices'], 3)]
    options = [correct_song] + decoys
    random.shuffle(options)
    return options, options.index(correct_song) + 1
