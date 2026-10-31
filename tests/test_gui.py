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
    setup.start_game.connect(lambda selected, language, difficulty: received.append((selected, language, difficulty)))

    setup.start()

    assert received == [(songs, "English", "easy")]


def test_game_disables_answers_and_updates_score(qt_app, songs):
    game = GameWidget(songs, "English", "easy")

    game.answer(0)

    assert all(not button.isEnabled() for button in game.answer_buttons)
    assert not game.next_button.isHidden()
    assert game.score >= 0


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
