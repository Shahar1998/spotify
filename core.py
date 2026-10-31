import random
import re
from collections import Counter

from models import Song


__version__ = "0.2.0"

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
        if pattern.search(cleaned_line) and len(cleaned_line) > 10:
            return f'Line Clue: "{pattern.sub("____", cleaned_line)}"'
    return "Line Clue: Contains the word '____'"


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


def build_round_options(songs, round_info):
    correct_song = songs[round_info['correct_idx']]
    decoys = [songs[index] for index in random.sample(round_info['decoy_indices'], 3)]
    options = [correct_song] + decoys
    random.shuffle(options)
    return options, options.index(correct_song) + 1
