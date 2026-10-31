import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

from gui_app import GameWidget, ResultsWidget, SetupWidget
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


def test_game_disables_answers_and_updates_score(qt_app, songs):
    game = GameWidget(songs, "English", "easy")

    game.answer(0)

    assert all(not button.isEnabled() for button in game.answer_buttons)
    assert not game.next_button.isHidden()
    assert game.score >= 0


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
