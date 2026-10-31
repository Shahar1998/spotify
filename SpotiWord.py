"""Backward-compatible public API for SpotiWord.

Use ``python cli.py`` for the terminal application or ``python gui_app.py``
for the desktop application.
"""

from cli import start_lyric_game
from core import (
    __version__,
    build_round_options,
    calculate_round_score,
    get_decoy_indices,
    get_lyric_snippet_clue,
    get_stop_words,
    is_hebrew,
    prepare_game_rounds,
    strip_hebrew_niqqud,
    tokenize_words,
)
from spotify_service import (
    LoadingCancelled,
    clean_track_name,
    create_spotify_client,
    load_and_categorize_songs,
)


if __name__ == '__main__':
    from cli import main

    main()
