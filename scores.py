import sqlite3
from datetime import datetime, timezone

from config import USER_DATA_PATH


DATABASE_PATH = USER_DATA_PATH / "scores.db"


def _connect():
    USER_DATA_PATH.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            language TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            score INTEGER NOT NULL,
            correct_answers INTEGER NOT NULL,
            total_rounds INTEGER NOT NULL,
            best_streak INTEGER NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def save_score(result):
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO scores (
                created_at, language, difficulty, score,
                correct_answers, total_rounds, best_streak
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                result['language'],
                result['difficulty'],
                result['score'],
                result['correct_answers'],
                result['total_rounds'],
                result['best_streak'],
            ),
        )


def top_scores(limit=10):
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT language, difficulty, score, correct_answers,
                   total_rounds, best_streak, created_at
            FROM scores
            ORDER BY score DESC, best_streak DESC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            'language': row[0],
            'difficulty': row[1],
            'score': row[2],
            'correct_answers': row[3],
            'total_rounds': row[4],
            'best_streak': row[5],
            'created_at': row[6],
        }
        for row in rows
    ]
