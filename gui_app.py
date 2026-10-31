import sys
from threading import Event

from core import (
    __version__,
    build_round_options,
    calculate_round_score,
    is_hebrew,
    prepare_game_rounds,
)
from models import Song
from spotify_service import LoadingCancelled, create_spotify_client, load_and_categorize_songs
from PySide6.QtCore import QElapsedTimer, QObject, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class LibraryLoader(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, max_songs):
        super().__init__()
        self.max_songs = max_songs
        self.cancel_requested = Event()

    @Slot()
    def cancel(self):
        self.cancel_requested.set()

    @Slot()
    def run(self):
        try:
            client = create_spotify_client()
            result = load_and_categorize_songs(
                client,
                max_songs=self.max_songs,
                progress_callback=self.progress.emit,
                cancel_callback=self.cancel_requested.is_set,
            )
            self.finished.emit(*result)
        except LoadingCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))


class SetupWidget(QWidget):
    start_game = Signal(object, str, str)

    def __init__(self, english_songs, hebrew_songs):
        super().__init__()
        self.english_songs = english_songs
        self.hebrew_songs = hebrew_songs

        title = QLabel("Ready for your next round?")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Choose a language and difficulty to begin.")
        subtitle.setObjectName("mutedText")

        self.language_combo = QComboBox()
        self.language_combo.addItem("English Songs", "English")
        self.language_combo.addItem("Hebrew Songs", "Hebrew")
        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItem("Easy - signature words", "easy")
        self.difficulty_combo.addItem("Hard - deeper cuts", "hard")

        start_button = QPushButton("Start Game")
        start_button.setObjectName("primaryButton")
        start_button.clicked.connect(self.start)

        card = QFrame()
        card.setObjectName("panel")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(16)
        card_layout.addWidget(QLabel("Language"))
        card_layout.addWidget(self.language_combo)
        card_layout.addWidget(QLabel("Difficulty"))
        card_layout.addWidget(self.difficulty_combo)
        card_layout.addSpacing(12)
        card_layout.addWidget(start_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

    @Slot()
    def start(self):
        language = self.language_combo.currentData()
        difficulty = self.difficulty_combo.currentData()
        songs = self.hebrew_songs if language == "Hebrew" else self.english_songs
        self.start_game.emit(songs, language, difficulty)


class GameWidget(QWidget):
    finished = Signal(object)

    def __init__(self, songs, language, difficulty):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft if language == "Hebrew" else Qt.LeftToRight)
        self.rounds = prepare_game_rounds(songs, difficulty)
        if not self.rounds:
            raise ValueError(f"No suitable rounds found for the {language} song pool.")

        self.songs = songs
        self.round_number = 0
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.correct_answers = 0
        self.options = []
        self.correct_option = 0
        self.answer_buttons = []
        self.link_buttons = []
        self.elapsed_timer = QElapsedTimer()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.network_manager = QNetworkAccessManager(self)
        self.active_art_reply = None

        self.round_label = QLabel()
        self.score_label = QLabel()
        self.streak_label = QLabel()
        self.timer_label = QLabel()
        self.word_label = QLabel()
        self.word_label.setObjectName("signatureWord")
        self.clue_label = QLabel()
        self.clue_label.setObjectName("clueText")
        self.clue_label.setWordWrap(True)
        self.clue_label.setAlignment(Qt.AlignCenter)
        self.album_art_label = QLabel()
        self.album_art_label.setFixedSize(250, 250)
        self.album_art_label.setAlignment(Qt.AlignCenter)
        self.album_art_label.setScaledContents(True)
        self.album_art_label.setVisible(False)
        self.result_label = QLabel()
        self.result_label.setObjectName("resultText")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.next_button = QPushButton("Next Round")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_round)
        self.next_button.setVisible(False)

        stats = QHBoxLayout()
        stats.addWidget(self.round_label)
        stats.addStretch()
        stats.addWidget(self.score_label)
        stats.addWidget(self.streak_label)
        stats.addWidget(self.timer_label)

        clue_panel = QFrame()
        clue_panel.setObjectName("cluePanel")
        clue_layout = QVBoxLayout(clue_panel)
        clue_layout.addWidget(self.word_label)
        clue_layout.addWidget(self.clue_label)

        answers = QGridLayout()
        for number in range(4):
            button = QPushButton()
            button.setObjectName("answerButton")
            button.setMinimumHeight(64)
            button.setProperty("state", "neutral")
            button.clicked.connect(lambda checked=False, n=number: self.answer(n))
            self.answer_buttons.append(button)
            answers.addWidget(button, number // 2, number % 2)

        links = QHBoxLayout()
        for _ in range(4):
            link_button = QPushButton()
            link_button.setObjectName("linkButton")
            link_button.setVisible(False)
            self.link_buttons.append(link_button)
            links.addWidget(link_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addLayout(stats)
        layout.addWidget(clue_panel)
        layout.addWidget(self.album_art_label, alignment=Qt.AlignCenter)
        layout.addLayout(answers)
        layout.addLayout(links)
        layout.addWidget(self.result_label)
        layout.addWidget(self.next_button)
        self.show_round()

    def show_round(self):
        round_info = self.rounds[self.round_number]
        self.options, self.correct_option = build_round_options(self.songs, round_info)
        self.round_label.setText(f"ROUND {self.round_number + 1} / {len(self.rounds)}")
        self.score_label.setText(f"SCORE {self.score}")
        self.streak_label.setText(f"STREAK {self.streak}")
        self.word_label.setText(round_info['target_word'].upper())
        self.clue_label.setText(round_info['clue'])
        self.clue_label.setAlignment(
            Qt.AlignRight if is_hebrew(round_info['clue']) else Qt.AlignLeft
        )
        self.album_art_label.clear()
        self.album_art_label.setVisible(False)
        self.result_label.clear()
        self.next_button.setVisible(False)

        for button, option in zip(self.answer_buttons, self.options):
            button.setText(f"{option.track_name} — {option.artist}")
            button.setEnabled(True)
            button.setProperty("state", "neutral")
            button.style().unpolish(button)
            button.style().polish(button)
        for link_button in self.link_buttons:
            link_button.setVisible(False)

        self.elapsed_timer.start()
        self.clock_timer.start(100)
        self.update_clock()

    @Slot()
    def update_clock(self):
        self.timer_label.setText(f"{self.elapsed_timer.elapsed() / 1000:.1f}s")

    @Slot(int)
    def answer(self, selected_index):
        elapsed = self.elapsed_timer.elapsed() / 1000
        self.clock_timer.stop()
        for button in self.answer_buttons:
            button.setEnabled(False)

        is_correct = selected_index + 1 == self.correct_option
        if is_correct:
            self.streak += 1
            self.correct_answers += 1
            self.best_streak = max(self.best_streak, self.streak)
            points = calculate_round_score(True, elapsed, self.streak)
            self.score += points
            self.answer_buttons[selected_index].setProperty("state", "correct")
            self.result_label.setText(f"Correct!  +{points} points")
        else:
            self.streak = 0
            self.answer_buttons[selected_index].setProperty("state", "wrong")
            self.answer_buttons[self.correct_option - 1].setProperty("state", "correct")
            correct = self.options[self.correct_option - 1]
            self.result_label.setText(f"The answer was {correct.track_name} — {correct.artist}")

        for button in self.answer_buttons:
            button.style().unpolish(button)
            button.style().polish(button)
        self.score_label.setText(f"SCORE {self.score}")
        self.streak_label.setText(f"STREAK {self.streak}")

        for link_button, option in zip(self.link_buttons, self.options):
            link_button.setText(f"Open {option.track_name}")
            try:
                link_button.clicked.disconnect()
            except TypeError:
                pass
            link_button.clicked.connect(lambda checked=False, url=option.spotify_url: QDesktopServices.openUrl(QUrl(url)))
            link_button.setVisible(bool(option.spotify_url))

        self.load_album_art(self.options[self.correct_option - 1].album_art_url)
        self.next_button.setText("Finish Game" if self.round_number + 1 == len(self.rounds) else "Next Round")
        self.next_button.setVisible(True)

    def load_album_art(self, image_url):
        if not image_url:
            return
        if self.active_art_reply:
            self.active_art_reply.abort()
        self.active_art_reply = self.network_manager.get(QNetworkRequest(QUrl(image_url)))
        self.active_art_reply.finished.connect(self.album_art_loaded)

    @Slot()
    def album_art_loaded(self):
        reply = self.active_art_reply
        self.active_art_reply = None
        if not reply or reply.error():
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(reply.readAll()):
            self.album_art_label.setPixmap(pixmap)
            self.album_art_label.setVisible(True)
        reply.deleteLater()

    @Slot()
    def next_round(self):
        if self.round_number + 1 == len(self.rounds):
            self.finished.emit({
                'score': self.score,
                'correct_answers': self.correct_answers,
                'total_rounds': len(self.rounds),
                'best_streak': self.best_streak,
            })
            return
        self.round_number += 1
        self.show_round()


class ResultsWidget(QWidget):
    play_again = Signal()

    def __init__(self, result):
        super().__init__()
        title = QLabel("GAME COMPLETE")
        title.setObjectName("pageTitle")
        score = QLabel(str(result['score']))
        score.setObjectName("finalScore")
        accuracy = result['correct_answers'] / result['total_rounds'] * 100
        summary = QLabel(
            f"Accuracy: {accuracy:.0f}%\nBest streak: {result['best_streak']}"
        )
        summary.setObjectName("mutedText")
        replay = QPushButton("Play Again")
        replay.setObjectName("primaryButton")
        replay.clicked.connect(self.play_again)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch()
        layout.addWidget(title, alignment=Qt.AlignCenter)
        layout.addWidget(QLabel("FINAL SCORE"), alignment=Qt.AlignCenter)
        layout.addWidget(score, alignment=Qt.AlignCenter)
        layout.addWidget(summary, alignment=Qt.AlignCenter)
        layout.addSpacing(20)
        layout.addWidget(replay)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.loader = None
        self.english_songs = None
        self.hebrew_songs = None
        self.setWindowTitle(f"SpotiWord v{__version__}")
        self.setMinimumSize(760, 700)

        self.status_label = QLabel("Ready to load your Spotify library.")
        self.status_label.setObjectName("mutedText")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.song_count = QSpinBox()
        self.song_count.setRange(20, 200)
        self.song_count.setSingleStep(10)
        self.song_count.setValue(100)
        self.song_count.setSuffix(" songs")
        self.start_button = QPushButton("Load Random Songs")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_loading)
        self.cancel_button = QPushButton("Cancel Loading")
        self.cancel_button.clicked.connect(self.cancel_loading)
        self.cancel_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(48, 48, 48, 48)
        brand = QLabel(f"SPOTIWORD  <span class='version'>v{__version__}</span>")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(20)
        layout.addWidget(QLabel("Number of songs to sample:"))
        layout.addWidget(self.song_count)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.start_button)
        layout.addWidget(self.cancel_button)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    @Slot()
    def start_loading(self):
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Connecting to Spotify...")
        self.progress_bar.setRange(0, 0)
        self.thread = QThread(self)
        self.loader = LibraryLoader(self.song_count.value())
        self.loader.moveToThread(self.thread)
        self.thread.started.connect(self.loader.run)
        self.loader.progress.connect(self.update_progress)
        self.loader.finished.connect(self.loading_finished)
        self.loader.failed.connect(self.loading_failed)
        self.loader.cancelled.connect(self.loading_cancelled)
        self.loader.finished.connect(self.thread.quit)
        self.loader.failed.connect(self.thread.quit)
        self.loader.cancelled.connect(self.thread.quit)
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
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Loading failed.")
        QMessageBox.critical(self, "SpotiWord Error", message)

    @Slot()
    def cancel_loading(self):
        if self.loader:
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling loading...")
            self.loader.cancel()

    @Slot()
    def loading_cancelled(self):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Loading cancelled.")

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
        game.finished.connect(self.show_results)
        self.setCentralWidget(game)

    @Slot(object)
    def show_results(self, result):
        results = ResultsWidget(result)
        results.play_again.connect(self.show_setup)
        self.setCentralWidget(results)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(
        """
        QWidget { background: #121212; color: #f5f5f5; font-size: 14px; }
        QFrame#panel, QFrame#cluePanel { background: #202020; border: 1px solid #333333; border-radius: 16px; }
        QLabel#brand { color: #1ed760; font-size: 24px; font-weight: 700; }
        QLabel#pageTitle { font-size: 28px; font-weight: 700; }
        QLabel#mutedText { color: #a7a7a7; }
        QLabel#signatureWord { color: #1ed760; font-size: 34px; font-weight: 800; }
        QLabel#clueText { color: #ffffff; font-size: 18px; padding: 14px; }
        QLabel#resultText { color: #1ed760; font-size: 17px; font-weight: 700; }
        QLabel#finalScore { color: #1ed760; font-size: 64px; font-weight: 800; }
        QPushButton { background: #282828; color: #ffffff; border: 1px solid #444444; padding: 12px; border-radius: 8px; }
        QPushButton:hover { background: #333333; border-color: #1ed760; }
        QPushButton#primaryButton { background: #1db954; border: none; font-weight: 700; }
        QPushButton#primaryButton:hover { background: #1ed760; }
        QPushButton#answerButton { font-size: 15px; text-align: left; padding: 16px; }
        QPushButton#answerButton[state="correct"] { background: #1db954; border-color: #1ed760; }
        QPushButton#answerButton[state="wrong"] { background: #e22134; border-color: #ff5364; }
        QPushButton#linkButton { color: #b3b3b3; border: none; font-size: 11px; padding: 5px; }
        QPushButton:disabled { background: #242424; color: #777777; }
        QComboBox, QSpinBox { background: #282828; color: #ffffff; padding: 10px; border: 1px solid #444444; border-radius: 6px; }
        QProgressBar { background: #282828; border: none; border-radius: 5px; height: 10px; text-align: center; }
        QProgressBar::chunk { background: #1db954; border-radius: 5px; }
        """
    )
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
