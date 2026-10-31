import time

from core import build_round_options, calculate_round_score, prepare_game_rounds
from spotify_service import create_spotify_client, load_and_categorize_songs
from core import __version__


def start_lyric_game(songs, language_name, difficulty_level):
    if len(songs) < 4:
        print(f"\nNot enough {language_name} songs found to start a game session (minimum 4 required).")
        return

    selected_rounds = prepare_game_rounds(songs, difficulty_level)
    if not selected_rounds:
        print(f"\nNo suitable signature words found in your {language_name} song pool.")
        return

    score = 0
    streak = 0
    print("\n" + "=" * 50)
    print(f"SpotiWord v{__version__}")
    print(f"WELCOME TO SPOTIWORD ({language_name.upper()} - {difficulty_level.upper()} MODE)!")
    print("=" * 50 + "\n")

    for round_number, round_info in enumerate(selected_rounds, 1):
        options, correct_option = build_round_options(songs, round_info)
        print(f"\n--- Round {round_number} of {len(selected_rounds)} | Score: {score} | Streak: {streak} ---")
        print(f"Signature Word: {round_info['target_word'].upper()}")
        print(f"{round_info['clue']}\n")
        for number, option in enumerate(options, 1):
            print(f"  [{number}] {option.track_name} — {option.artist}")

        start_time = time.monotonic()
        while True:
            try:
                guess = int(input("\nYour choice (1-4): "))
                if 1 <= guess <= 4:
                    break
            except ValueError:
                pass
            print("Please enter a valid number between 1 and 4.")

        elapsed = time.monotonic() - start_time
        if guess == correct_option:
            streak += 1
            points = calculate_round_score(True, elapsed, streak)
            score += points
            print(f"Correct! (+{points} points)")
        else:
            streak = 0
            print(f"Wrong! The answer was: {options[correct_option - 1].track_name}")

        print("\nListen on Spotify:")
        for number, option in enumerate(options, 1):
            print(f"  [{number}] {option.track_name}: {option.spotify_url}")

    print(f"\nGAME OVER! Final Score: {score}")


def main():
    spotify_client = create_spotify_client()
    english_songs, hebrew_songs = load_and_categorize_songs(spotify_client, max_songs=100)

    print("Select Game Language:")
    print("  [1] English Songs")
    print("  [2] Hebrew Songs")
    language_choice = input("\nEnter choice (1 or 2): ").strip()
    songs = hebrew_songs if language_choice == '2' else english_songs
    language = 'Hebrew' if language_choice == '2' else 'English'

    print("\nSelect Difficulty Tier:")
    print("  [1] Easy (Top Signature Word)")
    print("  [2] Hard (Lyrical Deep-Cuts)")
    difficulty_choice = input("\nEnter choice (1 or 2): ").strip()
    difficulty = 'hard' if difficulty_choice == '2' else 'easy'
    start_lyric_game(songs, language, difficulty)


if __name__ == '__main__':
    main()
