import os
from importlib.util import find_spec

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if find_spec("PySide6") is None:
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from gui_app import (
    FillInGameWidget,
    GameWidget,
    LibraryLoader,
    MainWindow,
    ResultsWidget,
    SetupWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication, QLabel
from models import Song


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def songs():
    return [
        Song("Track One", "Artist A", "", "summer summer summer in the night", True),
        Song("Track Two", "Artist B", "", "ocean ocean ocean in the night", True),
        Song("Track Three", "Artist C", "", "mountain mountain mountain in the night", True),
        Song("Track Four", "Artist D", "", "forest forest forest in the night", True),
    ]


def test_setup_emits_selected_game_configuration(qt_app, songs):
    setup = SetupWidget(songs, songs)
    received = []
    setup.start_game.connect(lambda selected, language, difficulty, mode: received.append((selected, language, difficulty, mode)))

    setup.start()

    assert received == [(songs, "English", "easy", "classic")]


def test_setup_can_select_blitz_mode(qt_app, songs):
    setup = SetupWidget(songs, songs)
    setup.mode_combo.setCurrentIndex(1)
    received = []
    setup.start_game.connect(lambda *values: received.append(values))

    setup.start()

    assert received[0][3] == "blitz"


def test_game_setup_does_not_repeat_source_filters(qt_app, songs):
    setup = SetupWidget(songs, songs)

    assert not hasattr(setup, "genre_combo")
    assert not hasattr(setup, "decade_combo")


def test_catalog_pool_shortfall_is_displayed(qt_app, songs):
    notice = MainWindow._catalog_pool_notice(
        {"kind": "catalog", "language": "English"},
        songs,
        [],
        100,
    )
    setup = SetupWidget(songs, [], pool_notice=notice)

    assert any(
        "4 playable songs out of 100 requested within the 20-page search sample"
        in label.text()
        for label in setup.findChildren(QLabel)
    )


def test_library_loader_prints_filters_counts_and_elapsed_time(
    monkeypatch, capsys
):
    song = Song(
        "Rock Song",
        "Artist",
        "",
        "lyrics",
        True,
        genres=("rock",),
        release_year=1995,
    )
    monkeypatch.setattr("gui_app.create_spotify_client", lambda: object())
    monkeypatch.setattr(
        "gui_app.load_and_categorize_songs",
        lambda *args, **kwargs: ([song], []),
    )
    times = iter((10.0, 12.5))
    monkeypatch.setattr("gui_app.perf_counter", lambda: next(times))
    loader = LibraryLoader(
        20,
        {
            "kind": "playlist",
            "genre": "Rock",
            "decade": 1990,
            "language": "English",
        },
    )

    loader.run()
    output = capsys.readouterr().out

    assert "source=playlist language=English genre=Rock decade=1990s requested=20" in output
    assert "loaded=1 (English=1 Hebrew=0) elapsed=2.50s" in output


def test_source_setup_exposes_catalog_filters(qt_app):
    from gui_app import SourceSetupWidget

    setup = SourceSetupWidget([
        {"id": None, "name": "Spotify Catalog", "kind": "catalog"},
        {"id": None, "name": "Liked Songs", "kind": "liked"},
    ])

    assert not setup.genre_combo.isHidden()
    assert setup.decade_combo.findData(1990) >= 0
    assert setup.language_combo.currentData() == "English"

    setup.genre_combo.setCurrentIndex(setup.genre_combo.findData("Rock"))
    setup.decade_combo.setCurrentIndex(setup.decade_combo.findData(1990))
    received = []
    setup.load_source.connect(lambda count, source: received.append((count, source)))
    setup.start_loading()

    assert received[0][1]["genre"] == "Rock"
    assert received[0][1]["decade"] == 1990
    assert received[0][1]["language"] == "English"


def test_main_window_starts_fill_in_widget_for_fill_in_mode(qt_app, songs):
    window = MainWindow()

    window.start_game(songs, "English", "easy", "fill_in")

    assert isinstance(window.centralWidget(), FillInGameWidget)


def test_game_disables_answers_and_updates_score(qt_app, songs):
    game = GameWidget(songs, "English", "easy")

    round_info = game.rounds[game.round_number]
    rendered_headline = QTextDocument()
    rendered_headline.setHtml(game.headline_label.text())

    assert game.headline_label.wordWrap()
    assert "Line Clue" not in game.headline_label.text()
    assert round_info["clue"] in rendered_headline.toPlainText()
    assert game.headline_label.text() == (
        f'<span style="color: #1ed760;">{round_info["clue"]}</span>'
    )
    assert game.headline_label.alignment() & Qt.AlignLeft
    assert game.headline_label.layoutDirection() == Qt.LeftToRight

    game.answer(0)

    assert all(not button.isEnabled() for button in game.answer_buttons)
    assert not game.next_button.isHidden()
    assert game.score >= 0


def test_hebrew_game_headline_uses_right_to_left_layout(qt_app, songs):
    game = GameWidget(songs, "Hebrew", "easy")

    assert game.headline_label.alignment() & Qt.AlignRight
    assert game.headline_label.layoutDirection() == Qt.RightToLeft


def test_blitz_game_shows_countdown_bar(qt_app, songs):
    game = GameWidget(songs, "English", "easy", "blitz")

    assert not game.time_bar.isHidden()
    assert game.time_bar.maximum() == 60_000
    assert game.timer_label.text().startswith("TIME ")
    game.finish_game()


def test_game_can_toggle_sound_feedback(qt_app, songs):
    game = GameWidget(songs, "English", "easy")

    assert game.sounds.enabled is True
    game.toggle_sound()

    assert game.sounds.enabled is False
    assert "Off" in game.sound_button.text()


def test_game_powerups_are_one_use(qt_app, songs):
    game = GameWidget(songs, "English", "easy", "blitz")

    game.use_fifty_fifty()
    game.use_time_boost()

    assert game.used_fifty_fifty is True
    assert game.used_time_boost is True
    assert game.fifty_button.isEnabled() is False
    assert game.time_boost_button.isEnabled() is False


def test_results_widget_displays_achievements(qt_app):
    result = {
        "score": 100,
        "correct_answers": 3,
        "total_rounds": 3,
        "best_streak": 3,
        "language": "English",
        "difficulty": "easy",
        "achievements": ["Perfect run"],
    }
    results = ResultsWidget(result, [])

    assert any("Perfect run" in label.text() for label in results.findChildren(QLabel))


def test_results_widget_displays_final_score(qt_app):
    result = {
        "score": 75,
        "correct_answers": 3,
        "total_rounds": 5,
        "best_streak": 2,
        "language": "English",
        "difficulty": "easy",
    }
    results = ResultsWidget(result, [result])

    assert any(label.text() == "75" for label in results.findChildren(QLabel))
