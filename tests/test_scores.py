from scores import save_score, top_scores


def test_scores_are_saved_and_sorted(tmp_path, monkeypatch):
    import scores

    monkeypatch.setattr(scores, "DATABASE_PATH", tmp_path / "scores.db")
    monkeypatch.setattr(scores, "USER_DATA_PATH", tmp_path)

    save_score({
        'language': 'English', 'difficulty': 'easy', 'score': 25,
        'correct_answers': 1, 'total_rounds': 1, 'best_streak': 1,
    })
    save_score({
        'language': 'Hebrew', 'difficulty': 'hard', 'score': 50,
        'correct_answers': 2, 'total_rounds': 2, 'best_streak': 2,
    })

    scores = top_scores()

    assert scores[0]['score'] == 50
    assert len(scores) == 2
