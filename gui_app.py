import sys
import logging
import math
import random
import re
import struct
from pathlib import Path
from threading import Event
from time import perf_counter

from core import (
    __version__,
    GENRE_FILTERS,
    build_fillin_options,
    build_round_options,
    calculate_round_score,
    is_hebrew,
    filter_songs,
    prepare_fillin_rounds,
    prepare_game_rounds,
)
from config import configure_logging, missing_configuration, resource_directory, save_configuration
from models import Song
from scores import save_score, top_scores
from spotify_service import (
    LoadingCancelled,
    create_spotify_client,
    list_spotify_sources,
    load_and_categorize_songs,
    start_track_playback,
)
from PySide6.QtCore import (
    QByteArray,
    QBuffer,
    QElapsedTimer,
    QIODevice,
    QObject,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SoundEffects(QObject):
    """Small synthesized UI sounds that require no external audio files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = True
        self._active = []

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled

    def play_correct(self):
        # Bright ascending C-major arpeggio.
        self._play_sequence([(1047, 75), (1319, 75), (1568, 120)])

    def play_wrong(self):
        # Gentle descending cue instead of a harsh buzzer.
        self._play_sequence([(330, 110), (247, 160)], volume=0.18)

    def play_tick(self):
        self._play_sequence([(900, 45)], volume=0.16)

    def play_streak(self):
        # Longer celebratory C-major fanfare for a five-answer streak.
        self._play_sequence(
            [(523, 80), (659, 80), (784, 80), (1047, 100), (1319, 220)],
            volume=0.28,
        )

    def _play_sequence(self, notes, volume=0.24):
        if not self.enabled:
            return
        sample_rate = 44_100
        raw = bytearray()
        for frequency, duration_ms in notes:
            sample_count = int(sample_rate * duration_ms / 1000)
            for index in range(sample_count):
                envelope = min(1.0, index / 220) * min(1.0, (sample_count - index) / 500)
                value = int(
                    32767
                    * volume
                    * envelope
                    * math.sin(2 * math.pi * frequency * index / sample_rate)
                )
                raw.extend(struct.pack("<h", value))
            raw.extend(b"\x00\x00" * int(sample_rate * 0.025))

        try:
            output_device = QMediaDevices.defaultAudioOutput()
            if output_device.isNull():
                logging.warning("No default audio output device is available")
                return
            audio_format = QAudioFormat()
            audio_format.setSampleRate(sample_rate)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not output_device.isFormatSupported(audio_format):
                audio_format = output_device.preferredFormat()
            sink = QAudioSink(output_device, audio_format, self)
            sink.setVolume(1.0)
            buffer = QBuffer(self)
            buffer.setData(QByteArray(bytes(raw)))
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            sink.start(buffer)
            self._active.append((sink, buffer))
            duration_ms = int(len(raw) / 2 / sample_rate * 1000) + 300
            QTimer.singleShot(duration_ms, lambda: self._cleanup(sink, buffer))
            logging.debug("Played sound effect; audio state=%s", sink.state())
        except Exception:
            # Audio is optional; an unavailable output device must not break gameplay.
            logging.debug("Audio feedback is unavailable", exc_info=True)

    def _cleanup(self, sink, buffer):
        sink.stop()
        buffer.close()
        try:
            self._active.remove((sink, buffer))
        except ValueError:
            pass


class LibraryLoader(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object, object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, max_songs, source):
        super().__init__()
        self.max_songs = max_songs
        self.source = source
        self.cancel_requested = Event()

    @Slot()
    def cancel(self):
        self.cancel_requested.set()

    @Slot()
    def run(self):
        started_at = perf_counter()
        source_kind = self.source.get('kind', 'liked')
        language = self.source.get('language', 'All')
        genre = self.source.get('genre') or 'All'
        decade = self.source.get('decade')
        decade_label = f'{decade}s' if decade is not None else 'All'
        load_context = (
            f"source={source_kind} language={language} genre={genre} "
            f"decade={decade_label} requested={self.max_songs}"
        )
        print(f"[SpotiWord] Song loading started: {load_context}", flush=True)
        try:
            client = create_spotify_client()
            english_songs, hebrew_songs = load_and_categorize_songs(
                client,
                max_songs=self.max_songs,
                progress_callback=self.progress.emit,
                cancel_callback=self.cancel_requested.is_set,
                source=self.source,
            )
            if source_kind != 'catalog':
                english_songs = filter_songs(
                    english_songs,
                    genre=self.source.get('genre'),
                    decade=decade,
                )
                hebrew_songs = filter_songs(
                    hebrew_songs,
                    genre=self.source.get('genre'),
                    decade=decade,
                )
            elapsed = perf_counter() - started_at
            print(
                f"[SpotiWord] Song loading completed: {load_context} "
                f"loaded={len(english_songs) + len(hebrew_songs)} "
                f"(English={len(english_songs)} Hebrew={len(hebrew_songs)}) "
                f"elapsed={elapsed:.2f}s",
                flush=True,
            )
            self.finished.emit(english_songs, hebrew_songs)
        except LoadingCancelled:
            elapsed = perf_counter() - started_at
            print(
                f"[SpotiWord] Song loading cancelled: {load_context} "
                f"elapsed={elapsed:.2f}s",
                flush=True,
            )
            self.cancelled.emit()
        except Exception as error:
            elapsed = perf_counter() - started_at
            print(
                f"[SpotiWord] Song loading failed: {load_context} "
                f"error={type(error).__name__} elapsed={elapsed:.2f}s",
                flush=True,
            )
            logging.exception("Spotify library loading failed")
            self.failed.emit(str(error))


class SourceLoader(QObject):
    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            self.finished.emit(list_spotify_sources(create_spotify_client()))
        except Exception as error:
            logging.exception("Spotify source loading failed")
            self.failed.emit(str(error))


class PlaybackWorker(QObject):
    finished = Signal(bool, str)

    def __init__(self, spotify_uri):
        super().__init__()
        self.spotify_uri = spotify_uri

    @Slot()
    def run(self):
        try:
            client = create_spotify_client()
            start_track_playback(client, self.spotify_uri)
            self.finished.emit(True, "Playing the correct song on Spotify.")
        except Exception as error:
            logging.exception("Spotify playback failed")
            self.finished.emit(False, str(error))


class ConfigurationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Spotify Configuration")
        self.setMinimumWidth(520)

        self.client_id = QLineEdit()
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.Password)
        self.redirect_uri = QLineEdit("http://127.0.0.1:8888/callback")

        form = QFormLayout()
        form.addRow("Client ID", self.client_id)
        form.addRow("Client Secret", self.client_secret)
        form.addRow("Redirect URI", self.redirect_uri)

        instructions = QLabel(
            "Create these values in the Spotify Developer Dashboard. "
            "They are saved only to the local .env file."
        )
        instructions.setWordWrap(True)
        instructions.setObjectName("mutedText")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Connect SpotiWord to Spotify"))
        layout.addWidget(instructions)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @Slot()
    def save(self):
        values = {
            "SPOTIFY_CLIENT_ID": self.client_id.text(),
            "SPOTIFY_CLIENT_SECRET": self.client_secret.text(),
            "SPOTIFY_REDIRECT_URI": self.redirect_uri.text(),
        }
        if any(not value.strip() for value in values.values()):
            QMessageBox.warning(self, "Incomplete Configuration", "Please fill in every field.")
            return
        save_configuration(values)
        self.accept()


class SourceSetupWidget(QWidget):
    load_source = Signal(int, object)

    def __init__(self, sources):
        super().__init__()
        title = QLabel("Choose your music source")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Sample tracks from Liked Songs or one of your playlists.")
        subtitle.setObjectName("mutedText")
        self.source_combo = QComboBox()
        for source in sources:
            self.source_combo.addItem(source['name'], source)
        self.song_count = QSpinBox()
        self.song_count.setRange(20, 200)
        self.song_count.setSingleStep(10)
        self.song_count.setValue(100)
        self.song_count.setSuffix(" songs")
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "English")
        self.language_combo.addItem("Hebrew", "Hebrew")
        self.genre_combo = QComboBox()
        self.genre_combo.addItem("All genres", None)
        for genre in sorted(GENRE_FILTERS):
            self.genre_combo.addItem(genre, genre)
        self.decade_combo = QComboBox()
        self.decade_combo.addItem("All years", None)
        for decade in range(1960, 2030, 10):
            self.decade_combo.addItem(f"{decade}s", decade)
        load_button = QPushButton("Load Selected Source")
        load_button.setObjectName("primaryButton")
        load_button.clicked.connect(self.start_loading)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.addWidget(title)
        panel_layout.addWidget(subtitle)
        panel_layout.addSpacing(16)
        panel_layout.addWidget(QLabel("Library or playlist"))
        panel_layout.addWidget(self.source_combo)
        panel_layout.addWidget(QLabel("Playable song pool size"))
        panel_layout.addWidget(self.song_count)
        panel_layout.addWidget(QLabel("Language"))
        panel_layout.addWidget(self.language_combo)
        panel_layout.addWidget(QLabel("Genre (optional)"))
        panel_layout.addWidget(self.genre_combo)
        panel_layout.addWidget(QLabel("Release decade (optional)"))
        panel_layout.addWidget(self.decade_combo)
        panel_layout.addSpacing(12)
        panel_layout.addWidget(load_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.addStretch()
        layout.addWidget(panel)
        layout.addStretch()
    @Slot()
    def start_loading(self):
        source = dict(self.source_combo.currentData())
        source['genre'] = self.genre_combo.currentData()
        source['decade'] = self.decade_combo.currentData()
        source['language'] = self.language_combo.currentData()
        self.load_source.emit(self.song_count.value(), source)


class SetupWidget(QWidget):
    start_game = Signal(object, str, str, str)
    change_source = Signal()

    def __init__(
        self,
        english_songs,
        hebrew_songs,
        language="English",
        pool_notice=None,
    ):
        super().__init__()
        self.english_songs = english_songs
        self.hebrew_songs = hebrew_songs
        self.language = language

        title = QLabel("Ready for your next round?")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Choose a language and difficulty to begin.")
        subtitle.setObjectName("mutedText")

        self.difficulty_combo = QComboBox()
        self.difficulty_combo.addItem("Easy - signature words", "easy")
        self.difficulty_combo.addItem("Hard - deeper cuts", "hard")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Classic - 5 rounds", "classic")
        self.mode_combo.addItem("Blitz - 60 seconds", "blitz")
        self.mode_combo.addItem("Fill in the Blank - guess the word", "fill_in")

        start_button = QPushButton("Start Game")
        start_button.setObjectName("primaryButton")
        start_button.clicked.connect(self.start)
        change_source_button = QPushButton("Change Library / Playlist")
        change_source_button.clicked.connect(self.change_source)

        card = QFrame()
        card.setObjectName("panel")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        if pool_notice:
            notice = QLabel(pool_notice)
            notice.setObjectName("warningText")
            notice.setWordWrap(True)
            card_layout.addWidget(notice)
        card_layout.addSpacing(16)
        card_layout.addWidget(QLabel("Difficulty"))
        card_layout.addWidget(self.difficulty_combo)
        card_layout.addWidget(QLabel("Game mode"))
        card_layout.addWidget(self.mode_combo)
        card_layout.addSpacing(12)
        card_layout.addWidget(start_button)
        card_layout.addWidget(change_source_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 40, 48, 40)
        layout.addStretch()
        layout.addWidget(card)
        layout.addStretch()

    @Slot()
    def start(self):
        difficulty = self.difficulty_combo.currentData()
        mode = self.mode_combo.currentData()
        language = self.language
        songs = self.hebrew_songs if language == "Hebrew" else self.english_songs
        self.start_game.emit(songs, language, difficulty, mode)


class GameWidget(QWidget):
    finished = Signal(object)
    change_source = Signal()

    def __init__(self, songs, language, difficulty, mode="classic"):
        super().__init__()
        self.language = language
        self.difficulty = difficulty
        self.mode = mode
        self.blitz_total_ms = 60_000
        self.blitz_remaining_ms = self.blitz_total_ms
        self.blitz_bonus_ms = 0
        self.session_finished = False
        self.sounds = SoundEffects(self)
        self.last_tick_second = None
        self.setLayoutDirection(Qt.RightToLeft if language == "Hebrew" else Qt.LeftToRight)
        self.rounds = prepare_game_rounds(
            songs, difficulty, max_rounds=50 if mode == "blitz" else 5
        )
        if not self.rounds:
            raise ValueError(f"No suitable rounds found for the {language} song pool.")

        self.songs = songs
        self.round_number = 0
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.correct_answers = 0
        self.answered_rounds = 0
        self.answered_current_round = False
        self.used_fifty_fifty = False
        self.used_time_boost = False
        self.playback_enabled = False
        self.playback_thread = None
        self.playback_worker = None
        self.options = []
        self.correct_option = 0
        self.answer_buttons = []
        self.link_buttons = []
        self.elapsed_timer = QElapsedTimer()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.blitz_timer = QTimer(self)
        self.blitz_timer.timeout.connect(self.update_blitz_clock)
        self.network_manager = QNetworkAccessManager(self)
        self.active_art_reply = None

        self.round_label = QLabel()
        self.score_label = QLabel()
        self.streak_label = QLabel()
        self.timer_label = QLabel()
        self.sound_button = QPushButton("🔊 Sound On")
        self.sound_button.setObjectName("linkButton")
        self.sound_button.clicked.connect(self.toggle_sound)
        self.fifty_button = QPushButton("50/50")
        self.fifty_button.setObjectName("linkButton")
        self.fifty_button.clicked.connect(self.use_fifty_fifty)
        self.time_boost_button = QPushButton("+5 Seconds")
        self.time_boost_button.setObjectName("linkButton")
        self.time_boost_button.setVisible(mode == "blitz")
        self.time_boost_button.clicked.connect(self.use_time_boost)
        self.playback_toggle = QPushButton("Spotify: Off")
        self.playback_toggle.setObjectName("linkButton")
        self.playback_toggle.clicked.connect(self.toggle_playback)
        self.play_button = QPushButton("▶ Play Correct Song")
        self.play_button.setObjectName("linkButton")
        self.play_button.setVisible(False)
        self.play_button.clicked.connect(self.play_correct_song)
        self.time_bar = QProgressBar()
        self.time_bar.setRange(0, self.blitz_total_ms)
        self.time_bar.setValue(self.blitz_total_ms)
        self.time_bar.setTextVisible(False)
        self.time_bar.setVisible(mode == "blitz")
        self.headline_label = QLabel()
        self.headline_label.setObjectName("questionHeadline")
        self.headline_label.setWordWrap(True)
        self.headline_label.setTextFormat(Qt.PlainText)
        self.headline_label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        self.headline_label.setLayoutDirection(
            Qt.RightToLeft if language == "Hebrew" else Qt.LeftToRight
        )
        self.headline_label.setAlignment(
            (
                Qt.AlignRight | Qt.AlignAbsolute
                if language == "Hebrew"
                else Qt.AlignLeft | Qt.AlignAbsolute
            )
        )
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
        self.change_source_button = QPushButton("Change Library / Playlist")
        self.change_source_button.setObjectName("linkButton")
        self.change_source_button.clicked.connect(self.change_source)

        stats = QHBoxLayout()
        stats.addWidget(self.round_label)
        stats.addStretch()
        stats.addWidget(self.score_label)
        stats.addWidget(self.streak_label)
        stats.addWidget(self.timer_label)
        stats.addWidget(self.sound_button)

        clue_panel = QFrame()
        clue_panel.setObjectName("cluePanel")
        clue_layout = QVBoxLayout(clue_panel)
        clue_layout.addWidget(self.headline_label)

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
            link_button.clicked.connect(self.open_spotify_link)
            self.link_buttons.append(link_button)
            links.addWidget(link_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addLayout(stats)
        layout.addWidget(self.time_bar)
        powerups = QHBoxLayout()
        powerups.addWidget(self.fifty_button)
        powerups.addWidget(self.time_boost_button)
        powerups.addWidget(self.playback_toggle)
        layout.addLayout(powerups)
        layout.addWidget(clue_panel)
        layout.addWidget(self.album_art_label, alignment=Qt.AlignCenter)
        layout.addLayout(answers)
        layout.addLayout(links)
        layout.addWidget(self.result_label)
        layout.addWidget(self.play_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.change_source_button)
        self.show_round()

    def show_round(self):
        round_info = self.rounds[self.round_number]
        self.options, self.correct_option = build_round_options(self.songs, round_info)
        self.round_label.setText(f"ROUND {self.round_number + 1} / {len(self.rounds)}")
        self.score_label.setText(f"SCORE {self.score}")
        self.streak_label.setText(f"STREAK {self.streak}")
        self.headline_label.setText(round_info['clue'])
        self.album_art_label.clear()
        self.album_art_label.setVisible(False)
        self.result_label.clear()
        self.next_button.setVisible(False)
        self.play_button.setVisible(False)
        self.answered_current_round = False

        for button, option in zip(self.answer_buttons, self.options):
            button.setText(f"{option.track_name} — {option.artist}")
            button.setEnabled(True)
            button.setProperty("state", "neutral")
            button.style().unpolish(button)
            button.style().polish(button)
        for link_button in self.link_buttons:
            link_button.setVisible(False)

        self.elapsed_timer.start()
        if self.mode == "blitz":
            if self.round_number == 0:
                self.blitz_session_timer = QElapsedTimer()
                self.blitz_session_timer.start()
                self.last_tick_second = None
            self.blitz_timer.start(100)
            self.update_blitz_clock()
        else:
            self.clock_timer.start(100)
        self.update_clock()

    @Slot()
    def update_clock(self):
        if self.mode == "blitz":
            return
        self.timer_label.setText(f"{self.elapsed_timer.elapsed() / 1000:.1f}s")

    @Slot()
    def update_blitz_clock(self):
        if self.session_finished:
            return
        self.blitz_remaining_ms = max(
            0,
            self.blitz_total_ms
            + self.blitz_bonus_ms
            - self.blitz_session_timer.elapsed(),
        )
        self.time_bar.setValue(self.blitz_remaining_ms)
        self.timer_label.setText(f"TIME {self.blitz_remaining_ms / 1000:.1f}s")
        color = "#1db954" if self.blitz_remaining_ms > 30_000 else "#ffb703"
        if self.blitz_remaining_ms <= 15_000:
            color = "#e22134"
        self.time_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; border-radius: 5px; }}"
        )
        if self.blitz_remaining_ms == 0:
            self.finish_game("Time's up!")
        elif self.blitz_remaining_ms <= 7_000:
            remaining_second = math.ceil(self.blitz_remaining_ms / 1000)
            if remaining_second != self.last_tick_second:
                self.last_tick_second = remaining_second
                self.sounds.play_tick()

    @Slot(int)
    def answer(self, selected_index):
        if self.session_finished or self.answered_current_round:
            return
        if not self.answer_buttons[selected_index].isEnabled():
            return
        self.answered_current_round = True
        self.answered_rounds += 1
        elapsed = self.elapsed_timer.elapsed() / 1000
        if self.mode != "blitz":
            self.clock_timer.stop()
        for button in self.answer_buttons:
            button.setEnabled(False)

        is_correct = selected_index + 1 == self.correct_option
        if is_correct:
            self.streak += 1
            self.correct_answers += 1
            self.best_streak = max(self.best_streak, self.streak)
            points = calculate_round_score(True, elapsed, self.streak)
            if self.mode == "blitz":
                self.blitz_bonus_ms += 4_000
            self.score += points
            self.sounds.play_streak() if self.streak >= 5 else self.sounds.play_correct()
            self.answer_buttons[selected_index].setProperty("state", "correct")
            self.result_label.setText(f"Correct!  +{points} points")
        else:
            self.streak = 0
            if self.mode == "blitz":
                self.blitz_bonus_ms -= 5_000
            self.answer_buttons[selected_index].setProperty("state", "wrong")
            self.sounds.play_wrong()
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
            link_button.setProperty("spotify_url", option.spotify_url)
            link_button.setVisible(bool(option.spotify_url))

        self.load_album_art(self.options[self.correct_option - 1].album_art_url)
        self.play_button.setVisible(True)
        if self.playback_enabled:
            self.play_correct_song()
        self.next_button.setText(
            "Finish Game" if self.round_number + 1 == len(self.rounds) else "Next Question"
        )
        self.next_button.setVisible(True)

    @Slot()
    def use_fifty_fifty(self):
        if self.used_fifty_fifty or self.answered_current_round:
            return
        self.used_fifty_fifty = True
        self.fifty_button.setEnabled(False)
        wrong_indices = [
            index for index in range(4) if index != self.correct_option - 1
        ]
        for index in random.sample(wrong_indices, 2):
            self.answer_buttons[index].setEnabled(False)
            self.answer_buttons[index].setText("— eliminated —")

    @Slot()
    def use_time_boost(self):
        if self.mode != "blitz" or self.used_time_boost or self.session_finished:
            return
        self.used_time_boost = True
        self.time_boost_button.setEnabled(False)
        self.blitz_bonus_ms += 5_000
        self.update_blitz_clock()

    def achievements(self):
        earned = []
        if self.correct_answers:
            earned.append("First correct answer")
        if self.best_streak >= 3:
            earned.append("Three-answer streak")
        if self.best_streak >= 5:
            earned.append("Five-answer streak")
        if self.answered_rounds and self.correct_answers == self.answered_rounds:
            earned.append("Perfect run")
        return earned

    @Slot()
    def toggle_sound(self):
        enabled = self.sounds.toggle()
        self.sound_button.setText("🔊 Sound On" if enabled else "🔇 Sound Off")

    @Slot()
    def toggle_playback(self):
        self.playback_enabled = not self.playback_enabled
        self.playback_toggle.setText(
            "Spotify: On" if self.playback_enabled else "Spotify: Off"
        )

    @Slot()
    def play_correct_song(self):
        if not self.options:
            return
        correct_song = self.options[self.correct_option - 1]
        if not correct_song.spotify_uri:
            self.result_label.setText("This track cannot be played through Spotify.")
            return
        if self.playback_thread:
            try:
                if self.playback_thread.isRunning():
                    return
            except RuntimeError:
                # Qt has already destroyed the finished thread wrapper.
                self.playback_thread = None
                self.playback_worker = None
        self.result_label.setText("Connecting to Spotify playback...")
        self.play_button.setEnabled(False)
        self.play_button.setText("Connecting to Spotify...")
        self.playback_thread = QThread(self)
        self.playback_worker = PlaybackWorker(correct_song.spotify_uri)
        self.playback_worker.moveToThread(self.playback_thread)
        self.playback_thread.started.connect(self.playback_worker.run)
        self.playback_worker.finished.connect(self.playback_finished)
        self.playback_worker.finished.connect(self.playback_thread.quit)
        self.playback_thread.finished.connect(self.playback_thread_finished)
        self.playback_thread.finished.connect(self.playback_worker.deleteLater)
        self.playback_thread.finished.connect(self.playback_thread.deleteLater)
        self.playback_thread.start()

    @Slot(bool, str)
    def playback_finished(self, success, message):
        self.play_button.setEnabled(True)
        self.play_button.setText("▶ Play Correct Song")
        self.result_label.setText(message if success else f"Spotify playback unavailable: {message}")

    @Slot()
    def playback_thread_finished(self):
        self.playback_thread = None
        self.playback_worker = None

    @Slot()
    def open_spotify_link(self):
        url = self.sender().property("spotify_url")
        if url:
            QDesktopServices.openUrl(QUrl(url))

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
        if self.session_finished:
            return
        if self.round_number + 1 == len(self.rounds):
            self.finish_game()
            return
        self.round_number += 1
        self.show_round()

    def finish_game(self, message=None):
        if self.session_finished:
            return
        self.session_finished = True
        self.clock_timer.stop()
        self.blitz_timer.stop()
        for button in self.answer_buttons:
            button.setEnabled(False)
        if message:
            self.result_label.setText(message)
        self.finished.emit({
            'score': self.score,
            'correct_answers': self.correct_answers,
            'total_rounds': max(1, self.answered_rounds),
            'best_streak': self.best_streak,
            'language': self.language,
            'difficulty': self.difficulty,
            'mode': self.mode,
            'achievements': self.achievements(),
        })


class FillInGameWidget(QWidget):
    """Fill-in-the-blank mode: see the song and a blanked lyric, pick the missing word."""

    finished = Signal(object)
    change_source = Signal()

    def __init__(self, songs, language, difficulty):
        super().__init__()
        self.language = language
        self.difficulty = difficulty
        self.mode = "fill_in"
        self.setLayoutDirection(Qt.RightToLeft if language == "Hebrew" else Qt.LeftToRight)
        self.rounds = prepare_fillin_rounds(songs, difficulty)
        if not self.rounds:
            raise ValueError(f"No suitable fill-in rounds found for the {language} song pool.")

        self.songs = songs
        self.round_number = 0
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.correct_answers = 0
        self.answered_rounds = 0
        self.answered_current_round = False
        self.used_fifty_fifty = False
        self.options = []
        self.correct_option = 0
        self.answer_buttons = []
        self.elapsed_timer = QElapsedTimer()
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.sounds = SoundEffects(self)
        self.network_manager = QNetworkAccessManager(self)
        self.active_art_reply = None

        # Playback support
        self.playback_enabled = False
        self.playback_thread = None
        self.playback_worker = None

        # Header stats
        self.round_label = QLabel()
        self.score_label = QLabel()
        self.streak_label = QLabel()
        self.timer_label = QLabel()
        self.sound_button = QPushButton("🔊 Sound On")
        self.sound_button.setObjectName("linkButton")
        self.sound_button.clicked.connect(self.toggle_sound)
        self.fifty_button = QPushButton("50/50")
        self.fifty_button.setObjectName("linkButton")
        self.fifty_button.clicked.connect(self.use_fifty_fifty)
        self.playback_toggle = QPushButton("Spotify: Off")
        self.playback_toggle.setObjectName("linkButton")
        self.playback_toggle.clicked.connect(self.toggle_playback)
        self.play_button = QPushButton("▶ Play Song")
        self.play_button.setObjectName("linkButton")
        self.play_button.setVisible(False)
        self.play_button.clicked.connect(self.play_correct_song)

        # Song identity
        self.song_label = QLabel()
        self.song_label.setObjectName("signatureWord")
        self.song_label.setAlignment(Qt.AlignCenter)
        self.song_label.setWordWrap(True)

        # Album art
        self.album_art_label = QLabel()
        self.album_art_label.setFixedSize(180, 180)
        self.album_art_label.setAlignment(Qt.AlignCenter)
        self.album_art_label.setScaledContents(True)
        self.album_art_label.setVisible(False)

        # Blanked lyric clue
        self.clue_label = QLabel()
        self.clue_label.setObjectName("clueText")
        self.clue_label.setWordWrap(True)
        self.clue_label.setAlignment(Qt.AlignCenter)

        # Result feedback
        self.result_label = QLabel()
        self.result_label.setObjectName("resultText")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.next_button = QPushButton("Next Round")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_round)
        self.next_button.setVisible(False)
        self.change_source_button = QPushButton("Change Library / Playlist")
        self.change_source_button.setObjectName("linkButton")
        self.change_source_button.clicked.connect(self.change_source)

        # Layout
        stats = QHBoxLayout()
        stats.addWidget(self.round_label)
        stats.addStretch()
        stats.addWidget(self.score_label)
        stats.addWidget(self.streak_label)
        stats.addWidget(self.timer_label)
        stats.addWidget(self.sound_button)

        clue_panel = QFrame()
        clue_panel.setObjectName("cluePanel")
        clue_layout = QVBoxLayout(clue_panel)
        clue_layout.addWidget(self.song_label)
        clue_layout.addWidget(self.album_art_label, alignment=Qt.AlignCenter)
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

        powerups = QHBoxLayout()
        powerups.addWidget(self.fifty_button)
        powerups.addWidget(self.playback_toggle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addLayout(stats)
        layout.addLayout(powerups)
        layout.addWidget(clue_panel)
        layout.addLayout(answers)
        layout.addWidget(self.result_label)
        layout.addWidget(self.play_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.change_source_button)
        self.show_round()

    def show_round(self):
        round_info = self.rounds[self.round_number]
        song = self.songs[round_info['song_index']]
        self.options, self.correct_option = build_fillin_options(round_info)
        self.round_label.setText(f"ROUND {self.round_number + 1} / {len(self.rounds)}")
        self.score_label.setText(f"SCORE {self.score}")
        self.streak_label.setText(f"STREAK {self.streak}")
        self.song_label.setText(f"{song.track_name} — {song.artist}")
        self.clue_label.setText(f'"{round_info["blanked_line"]}"')
        self.clue_label.setAlignment(
            Qt.AlignRight if is_hebrew(round_info['blanked_line']) else Qt.AlignCenter
        )
        self.album_art_label.clear()
        self.album_art_label.setVisible(False)
        self.load_album_art(song.album_art_url)
        self.result_label.clear()
        self.next_button.setVisible(False)
        self.play_button.setVisible(False)
        self.answered_current_round = False

        for button, word in zip(self.answer_buttons, self.options):
            button.setText(word.upper())
            button.setEnabled(True)
            button.setProperty("state", "neutral")
            button.style().unpolish(button)
            button.style().polish(button)

        self.elapsed_timer.start()
        self.clock_timer.start(100)
        self.update_clock()

    @Slot()
    def update_clock(self):
        self.timer_label.setText(f"{self.elapsed_timer.elapsed() / 1000:.1f}s")

    @Slot(int)
    def answer(self, selected_index):
        if self.answered_current_round:
            return
        if not self.answer_buttons[selected_index].isEnabled():
            return
        self.answered_current_round = True
        self.answered_rounds += 1
        elapsed = self.elapsed_timer.elapsed() / 1000
        self.clock_timer.stop()
        for button in self.answer_buttons:
            button.setEnabled(False)

        is_correct = selected_index + 1 == self.correct_option
        round_info = self.rounds[self.round_number]
        if is_correct:
            self.streak += 1
            self.correct_answers += 1
            self.best_streak = max(self.best_streak, self.streak)
            points = calculate_round_score(True, elapsed, self.streak)
            self.score += points
            self.sounds.play_streak() if self.streak >= 5 else self.sounds.play_correct()
            self.answer_buttons[selected_index].setProperty("state", "correct")
            self.result_label.setText(f"Correct!  +{points} points — the word was \"{round_info['target_word']}\"")
        else:
            self.streak = 0
            self.sounds.play_wrong()
            self.answer_buttons[selected_index].setProperty("state", "wrong")
            self.answer_buttons[self.correct_option - 1].setProperty("state", "correct")
            self.result_label.setText(f"Wrong! The answer was \"{round_info['target_word']}\"")

        for button in self.answer_buttons:
            button.style().unpolish(button)
            button.style().polish(button)
        self.score_label.setText(f"SCORE {self.score}")
        self.streak_label.setText(f"STREAK {self.streak}")

        self.play_button.setVisible(True)
        if self.playback_enabled:
            self.play_correct_song()
        self.next_button.setText(
            "Finish Game" if self.round_number + 1 == len(self.rounds) else "Next Question"
        )
        self.next_button.setVisible(True)

    @Slot()
    def use_fifty_fifty(self):
        if self.used_fifty_fifty or self.answered_current_round:
            return
        self.used_fifty_fifty = True
        self.fifty_button.setEnabled(False)
        wrong_indices = [
            index for index in range(4) if index != self.correct_option - 1
        ]
        for index in random.sample(wrong_indices, 2):
            self.answer_buttons[index].setEnabled(False)
            self.answer_buttons[index].setText("—")

    def achievements(self):
        earned = []
        if self.correct_answers:
            earned.append("First correct answer")
        if self.best_streak >= 3:
            earned.append("Three-answer streak")
        if self.best_streak >= 5:
            earned.append("Five-answer streak")
        if self.answered_rounds and self.correct_answers == self.answered_rounds:
            earned.append("Perfect run")
        return earned

    @Slot()
    def toggle_sound(self):
        enabled = self.sounds.toggle()
        self.sound_button.setText("🔊 Sound On" if enabled else "🔇 Sound Off")

    @Slot()
    def toggle_playback(self):
        self.playback_enabled = not self.playback_enabled
        self.playback_toggle.setText(
            "Spotify: On" if self.playback_enabled else "Spotify: Off"
        )

    @Slot()
    def play_correct_song(self):
        round_info = self.rounds[self.round_number]
        song = self.songs[round_info['song_index']]
        if not song.spotify_uri:
            self.result_label.setText("This track cannot be played through Spotify.")
            return
        if self.playback_thread:
            try:
                if self.playback_thread.isRunning():
                    return
            except RuntimeError:
                self.playback_thread = None
                self.playback_worker = None
        self.play_button.setEnabled(False)
        self.play_button.setText("Connecting to Spotify...")
        self.playback_thread = QThread(self)
        self.playback_worker = PlaybackWorker(song.spotify_uri)
        self.playback_worker.moveToThread(self.playback_thread)
        self.playback_thread.started.connect(self.playback_worker.run)
        self.playback_worker.finished.connect(self.playback_finished)
        self.playback_worker.finished.connect(self.playback_thread.quit)
        self.playback_thread.finished.connect(self.playback_thread_finished)
        self.playback_thread.finished.connect(self.playback_worker.deleteLater)
        self.playback_thread.finished.connect(self.playback_thread.deleteLater)
        self.playback_thread.start()

    @Slot(bool, str)
    def playback_finished(self, success, message):
        self.play_button.setEnabled(True)
        self.play_button.setText("▶ Play Song")
        if not success:
            self.result_label.setText(f"Spotify playback unavailable: {message}")

    @Slot()
    def playback_thread_finished(self):
        self.playback_thread = None
        self.playback_worker = None

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
                'total_rounds': max(1, self.answered_rounds),
                'best_streak': self.best_streak,
                'language': self.language,
                'difficulty': self.difficulty,
                'mode': self.mode,
                'achievements': self.achievements(),
            })
            return
        self.round_number += 1
        self.show_round()


class ResultsWidget(QWidget):
    play_again = Signal()
    change_source = Signal()

    def __init__(self, result, scores):
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
        achievements = result.get("achievements", [])
        achievement_text = (
            "ACHIEVEMENTS\n" + "\n".join(f"🏆 {item}" for item in achievements)
            if achievements
            else "ACHIEVEMENTS\nNo achievements yet"
        )
        achievement_label = QLabel(achievement_text)
        achievement_label.setObjectName("mutedText")
        achievement_label.setAlignment(Qt.AlignCenter)
        leaderboard_text = "TOP SCORES\n"
        if scores:
            leaderboard_text += "\n".join(
                f"{index}. {item['score']} pts — {item['language']} / {item['difficulty']}"
                for index, item in enumerate(scores, 1)
            )
        else:
            leaderboard_text += "No scores yet"
        leaderboard = QLabel(leaderboard_text)
        leaderboard.setObjectName("mutedText")
        leaderboard.setAlignment(Qt.AlignCenter)
        replay = QPushButton("Play Again")
        replay.setObjectName("primaryButton")
        replay.clicked.connect(self.play_again)
        change_source = QPushButton("Change Library / Playlist")
        change_source.setObjectName("linkButton")
        change_source.clicked.connect(self.change_source)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch()
        layout.addWidget(title, alignment=Qt.AlignCenter)
        layout.addWidget(QLabel("FINAL SCORE"), alignment=Qt.AlignCenter)
        layout.addWidget(score, alignment=Qt.AlignCenter)
        layout.addWidget(summary, alignment=Qt.AlignCenter)
        layout.addWidget(achievement_label, alignment=Qt.AlignCenter)
        layout.addWidget(leaderboard, alignment=Qt.AlignCenter)
        layout.addSpacing(20)
        layout.addWidget(replay)
        layout.addWidget(change_source)
        layout.addStretch()


class MainWindow(QMainWindow):
    @staticmethod
    def _catalog_pool_notice(source, english_songs, hebrew_songs, requested):
        if source.get('kind') != 'catalog':
            return None
        language = source.get('language', 'English')
        available = len(hebrew_songs if language == 'Hebrew' else english_songs)
        if available >= requested:
            return None
        return (
            f"Catalog found {available} playable songs out of "
            f"{requested} requested within the 20-page search sample. "
            "Try broader filters or request a smaller pool."
        )

    def __init__(self):
        super().__init__()
        self.thread = None
        self.loader = None
        self.source_thread = None
        self.source_loader = None
        self.english_songs = None
        self.hebrew_songs = None
        self.sources = []
        self.selected_source = None
        self.requested_pool_size = 100
        self.setWindowTitle(f"SpotiWord v{__version__}")
        icon_path = resource_directory() / "assets" / "spotiword.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(760, 700)

        self.show_loading_screen()

    def show_loading_screen(self):
        self.status_label = QLabel("Ready to load your Spotify library.")
        self.status_label.setObjectName("mutedText")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.song_count = QSpinBox()
        self.song_count.setRange(20, 200)
        self.song_count.setSingleStep(10)
        self.song_count.setValue(100)
        self.song_count.setSuffix(" songs")
        self.start_button = QPushButton("Choose Library Source")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_loading)
        self.settings_button = QPushButton("Spotify Settings")
        self.settings_button.setObjectName("linkButton")
        self.settings_button.clicked.connect(self.show_configuration)
        self.cancel_button = QPushButton("Cancel Loading")
        self.cancel_button.clicked.connect(self.cancel_loading)
        self.cancel_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(48, 48, 48, 48)
        brand = QLabel(f"SPOTIWORD  v{__version__}")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(20)
        layout.addWidget(QLabel("Connect to Spotify to choose a library or playlist:"))
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.start_button)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.cancel_button)
        container = QWidget()
        container.setLayout(layout)
        self.loading_container = container
        self.setCentralWidget(container)

    @Slot()
    def start_loading(self):
        if missing_configuration():
            if not self.show_configuration():
                return
        self.start_button.setEnabled(False)
        self.status_label.setText("Connecting to Spotify...")
        self.progress_bar.setRange(0, 0)
        self.source_thread = QThread(self)
        self.source_loader = SourceLoader()
        self.source_loader.moveToThread(self.source_thread)
        self.source_thread.started.connect(self.source_loader.run)
        self.source_loader.finished.connect(self.sources_loaded)
        self.source_loader.failed.connect(self.loading_failed)
        self.source_loader.finished.connect(self.source_thread.quit)
        self.source_loader.failed.connect(self.source_thread.quit)
        self.source_thread.finished.connect(self.source_thread.deleteLater)
        self.source_thread.finished.connect(self.source_loader.deleteLater)
        self.source_thread.start()

    @Slot(int, int, str)
    def update_progress(self, current, total, message):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(message)

    @Slot(object, object)
    def loading_finished(self, english_songs, hebrew_songs):
        self.english_songs = english_songs
        self.hebrew_songs = hebrew_songs
        source = self.selected_source or {}
        pool_notice = self._catalog_pool_notice(
            source,
            english_songs,
            hebrew_songs,
            self.requested_pool_size,
        )
        self.show_setup(pool_notice)

    @Slot(object)
    def sources_loaded(self, sources):
        self.sources = sources
        self.start_button.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.show_source_setup(sources)

    @Slot(str)
    def loading_failed(self, message):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Loading failed.")
        QMessageBox.critical(self, "SpotiWord Error", message)

    @Slot()
    def show_configuration(self):
        dialog = ConfigurationDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.status_label.setText("Spotify configuration saved.")
            return True
        return False

    @Slot()
    def cancel_loading(self):
        if self.loader:
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling loading...")
            self.loader.cancel()

    @Slot(int, object)
    def load_selected_source(self, max_songs, source):
        self.selected_source = source
        self.requested_pool_size = max_songs
        self.show_loading_screen()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(f"Loading {source['name']}...")
        self.progress_bar.setRange(0, 0)
        self.thread = QThread(self)
        self.loader = LibraryLoader(max_songs, source)
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

    @Slot()
    def loading_cancelled(self):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Loading cancelled.")

    def show_setup(self, pool_notice=None):
        language = (self.selected_source or {}).get('language', 'English')
        setup = SetupWidget(
            self.english_songs,
            self.hebrew_songs,
            language,
            pool_notice=pool_notice,
        )
        setup.start_game.connect(self.start_game)
        setup.change_source.connect(lambda: self.show_source_setup(self.sources))
        self.setCentralWidget(setup)

    def show_source_setup(self, sources):
        setup = SourceSetupWidget(sources)
        setup.load_source.connect(self.load_selected_source)
        self.setCentralWidget(setup)

    @Slot(object, str, str, str)
    def start_game(self, songs, language, difficulty, mode):
        try:
            if mode == "fill_in":
                game = FillInGameWidget(songs, language, difficulty)
            else:
                game = GameWidget(songs, language, difficulty, mode)
        except ValueError as error:
            QMessageBox.warning(self, "Unable to Start", str(error))
            return
        game.finished.connect(self.show_results)
        game.change_source.connect(self.confirm_change_source)
        self.setCentralWidget(game)

    @Slot(object)
    def show_results(self, result):
        save_score(result)
        results = ResultsWidget(result, top_scores())
        results.play_again.connect(self.show_setup)
        results.change_source.connect(lambda: self.show_source_setup(self.sources))
        self.setCentralWidget(results)

    @Slot()
    def confirm_change_source(self):
        answer = QMessageBox.question(
            self,
            "Change Library?",
            "Your current game will be discarded. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.show_source_setup(self.sources)


def main():
    configure_logging()
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(
        """
        QWidget { background: #121212; color: #f5f5f5; font-size: 14px; }
        QFrame#panel, QFrame#cluePanel { background: #202020; border: 1px solid #333333; border-radius: 16px; }
        QLabel#brand { color: #1ed760; font-size: 24px; font-weight: 700; }
        QLabel#pageTitle { font-size: 28px; font-weight: 700; }
        QLabel#mutedText { color: #a7a7a7; }
        QLabel#questionHeadline { color: #1ed760; font-size: 30px; font-weight: 700; padding: 14px; }
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
