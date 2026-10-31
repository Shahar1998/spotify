import sys

from SpotiWord import (
    __version__,
    build_round_options,
    calculate_round_score,
    create_spotify_client,
    load_and_categorize_songs,
    prepare_game_rounds,
)
from PySide6.QtCore import QElapsedTimer, QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QDesktopServices


class LibraryLoader(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, max_songs):
        super().__init__()
        self.max_songs = max_songs

    @Slot()
    def run(self):
        try:
            spotify_client = create_spotify_client()
            english_songs, hebrew_songs = load_and_categorize_songs(
                spotify_client,
                max_songs=self.max_songs,
                progress_callback=self.progress.emit,
            )
            self.finished.emit(english_songs, hebrew_songs)
        except Exception as error:
            self.failed.emit(str(error))


class SetupWidget(QWidget):
    start_game = Signal(object, str, str)

    def __init__(self, english_songs, hebrew_songs):
        super().__init__()
        self.english_songs = english_songs
        self.hebrew_songs = hebrew_songs

        self.language_combo = QComboBox()
        self.language_combo.addItem("English Songs", "English")
        self.language_combo.addItem("Hebrew Songs", "Hebrew")

        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItem("Easy", "easy")
        self.difficulty_combo.addItem("Hard", "hard")

        start_button = QPushButton("Start Game")
        start_button.clicked.connect(self.start)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose your game language:"))
        layout.addWidget(self.language_combo)
        layout.addWidget(QLabel("Choose difficulty:"))
        layout.addWidget(self.difficulty_combo)
        layout.addWidget(start_button)

    @Slot()
    def start(self):
        language = self.language_combo.currentData()
        difficulty = self.difficulty_combo.currentData()
        songs = self.hebrew_songs if language == "Hebrew" else self.english_songs
        self.start_game.emit(songs, language, difficulty)


class GameWidget(QWidget):
    finished = Signal(int)

    def __init__(self, songs, language, difficulty):
        super().__init__()
        self.rounds = prepare_game_rounds(songs, difficulty)
        if not self.rounds:
            raise ValueError(f"No suitable rounds found for the {language} song pool.")

        self.songs = songs
        self.round_number = 0
        self.score = 0
        self.streak = 0
        self.options = []
        self.correct_option = 0
        self.answer_buttons = []
        self.link_buttons = []
        self.elapsed_timer = QElapsedTimer()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)

        self.progress_label = QLabel()
        self.score_label = QLabel()
        self.timer_label = QLabel()
        self.word_label = QLabel()
        self.clue_label = QLabel()
        self.clue_label.setWordWrap(True)
        self.result_label = QLabel()
        self.next_button = QPushButton("Next Round")
        self.next_button.clicked.connect(self.next_round)
        self.next_button.setVisible(False)

        layout = QVBoxLayout(self)
        for widget in (
            self.progress_label,
            self.score_label,
            self.timer_label,
            self.word_label,
            self.clue_label,
        ):
            layout.addWidget(widget)

        for number in range(4):
            button = QPushButton()
            button.clicked.connect(lambda checked=False, n=number: self.answer(n))
            self.answer_buttons.append(button)
            layout.addWidget(button)

        for number in range(4):
            link_button = QPushButton()
            link_button.setVisible(False)
            self.link_buttons.append(link_button)
            layout.addWidget(link_button)

        layout.addWidget(self.result_label)
        layout.addWidget(self.next_button)
        self.show_round()

    def show_round(self):
        round_info = self.rounds[self.round_number]
        self.options, self.correct_option = build_round_options(self.songs, round_info)
        self.progress_label.setText(
            f"Round {self.round_number + 1} of {len(self.rounds)}"
        )
        self.score_label.setText(f"Score: {self.score}    Streak: {self.streak}")
        self.word_label.setText(f"Signature word: {round_info['target_word'].upper()}")
        self.clue_label.setText(round_info["clue"])
        self.result_label.clear()
        self.next_button.setVisible(False)

        for button, option in zip(self.answer_buttons, self.options):
            button.setText(f"{option['Track Name']} — {option['Artist']}")
            button.setEnabled(True)

        for link_button in self.link_buttons:
            link_button.setVisible(False)

        self.elapsed_timer.start()
        self.clock_timer.start(100)
        self.update_clock()

    @Slot()
    def update_clock(self):
        self.timer_label.setText(f"Time: {self.elapsed_timer.elapsed() / 1000:.1f}s")

    @Slot(int)
    def answer(self, selected_index):
        elapsed_time = self.elapsed_timer.elapsed() / 1000
        self.clock_timer.stop()
        for button in self.answer_buttons:
            button.setEnabled(False)

        if selected_index + 1 == self.correct_option:
            self.streak += 1
            points = calculate_round_score(True, elapsed_time, self.streak)
            self.score += points
            self.result_label.setText(f"Correct! +{points} points")
        else:
            self.streak = 0
            correct = self.options[self.correct_option - 1]
            self.result_label.setText(
                f"Incorrect. Correct answer: {correct['Track Name']} — {correct['Artist']}"
            )

        self.score_label.setText(f"Score: {self.score}    Streak: {self.streak}")
        for link_button, option in zip(self.link_buttons, self.options):
            link_button.setText(f"Open {option['Track Name']} in Spotify")
            try:
                link_button.clicked.disconnect()
            except TypeError:
                pass
            link_button.clicked.connect(
                lambda checked=False, url=option['Spotify URL']:
                QDesktopServices.openUrl(QUrl(url))
            )
            link_button.setVisible(bool(option['Spotify URL']))
        self.next_button.setText(
            "Finish Game" if self.round_number + 1 == len(self.rounds) else "Next Round"
        )
        self.next_button.setVisible(True)

    @Slot()
    def next_round(self):
        if self.round_number + 1 == len(self.rounds):
            self.finished.emit(self.score)
            return
        self.round_number += 1
        self.show_round()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.loader = None
        self.english_songs = None
        self.hebrew_songs = None

        self.setWindowTitle(f"SpotiWord v{__version__}")
        self.setMinimumSize(600, 420)

        self.status_label = QLabel("Ready to load your Spotify library.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.song_count = QSpinBox()
        self.song_count.setRange(20, 200)
        self.song_count.setSingleStep(10)
        self.song_count.setValue(200)
        self.song_count.setSuffix(" songs")
        self.start_button = QPushButton("Load Random Songs")
        self.start_button.clicked.connect(self.start_loading)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"SpotiWord v{__version__}"))
        layout.addWidget(QLabel("Number of songs to sample:"))
        layout.addWidget(self.song_count)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.start_button)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    @Slot()
    def start_loading(self):
        self.start_button.setEnabled(False)
        self.status_label.setText("Connecting to Spotify...")
        self.progress_bar.setRange(0, 0)

        self.thread = QThread(self)
        self.loader = LibraryLoader(self.song_count.value())
        self.loader.moveToThread(self.thread)
        self.thread.started.connect(self.loader.run)
        self.loader.progress.connect(self.update_progress)
        self.loader.finished.connect(self.loading_finished)
        self.loader.failed.connect(self.loading_failed)
        self.loader.finished.connect(self.thread.quit)
        self.loader.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.loader.deleteLater)
        self.thread.start()

    @Slot(int, int, str)
    def update_progress(self, current, total, message):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    @Slot(object, object)
    def loading_finished(self, english_songs, hebrew_songs):
        self.english_songs = english_songs
        self.hebrew_songs = hebrew_songs
        self.show_setup()

    @Slot(str)
    def loading_failed(self, message):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(True)
        self.status_label.setText("Loading failed.")
        QMessageBox.critical(self, "SpotiWord Error", message)

    def show_setup(self):
        setup = SetupWidget(self.english_songs, self.hebrew_songs)
        setup.start_game.connect(self.start_game)
        self.setCentralWidget(setup)

    @Slot(object, str, str)
    def start_game(self, songs, language, difficulty):
        try:
            game = GameWidget(songs, language, difficulty)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to Start", str(error))
            return
        game.finished.connect(self.game_finished)
        self.setCentralWidget(game)

    @Slot(int)
    def game_finished(self, score):
        QMessageBox.information(self, "Game Over", f"Final score: {score}")
        self.show_setup()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(
        """
        QWidget { background: #181818; color: #f2f2f2; font-size: 14px; }
        QPushButton { background: #1db954; color: #ffffff; border: none; padding: 10px; border-radius: 5px; }
        QPushButton:hover { background: #1ed760; }
        QPushButton:disabled { background: #555555; color: #aaaaaa; }
        QComboBox, QSpinBox { background: #282828; color: #ffffff; padding: 7px; border: 1px solid #555555; }
        QProgressBar { border: 1px solid #555555; text-align: center; }
        QProgressBar::chunk { background: #1db954; }
        """
    )
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
