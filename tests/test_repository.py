"""Tests for repository CRUD operations."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.db.repository import (
    PlayerRepo, GameRepo, StatsRepo, PropLineRepo, PredictionRepo, DefenseProfileRepo,
)


def test_player_upsert_creates(session):
    repo = PlayerRepo(session)
    player = repo.upsert("p1", name="John Doe", team="KC", position="QB")
    session.commit()

    fetched = repo.get("p1")
    assert fetched.name == "John Doe"


def test_player_upsert_updates(session):
    repo = PlayerRepo(session)
    repo.upsert("p1", name="John Doe", team="KC", position="QB")
    session.commit()

    repo.upsert("p1", team="SF")
    session.commit()

    fetched = repo.get("p1")
    assert fetched.team == "SF"
    assert fetched.name == "John Doe"


def test_player_find_by_name(session):
    repo = PlayerRepo(session)
    repo.upsert("p1", name="Patrick Mahomes", team="KC")
    session.commit()

    found = repo.find_by_name("Patrick Mahomes")
    assert found is not None
    assert found.player_id == "p1"


def test_player_find_by_name_fuzzy(session):
    repo = PlayerRepo(session)
    repo.upsert("p1", name="Patrick Mahomes", team="KC")
    session.commit()

    found = repo.find_by_name_fuzzy("Mahomes")
    assert found is not None
    assert found.player_id == "p1"


def test_game_upsert_and_find_by_week(session):
    repo = GameRepo(session)
    repo.upsert("g1", season=2025, week=5, home_team="KC", away_team="BUF")
    repo.upsert("g2", season=2025, week=5, home_team="SF", away_team="DAL")
    session.commit()

    games = repo.find_by_week(2025, 5)
    assert len(games) == 2


def test_game_find_by_team(session):
    repo = GameRepo(session)
    repo.upsert("g1", season=2025, week=5, home_team="KC", away_team="BUF")
    repo.upsert("g2", season=2025, week=6, home_team="SF", away_team="KC")
    session.commit()

    games = repo.find_by_team("KC", 2025)
    assert len(games) == 2


def test_stats_upsert_and_query(session):
    PlayerRepo(session).upsert("p1", name="Test")
    GameRepo(session).upsert("g1", season=2025, week=1, home_team="A", away_team="B")
    GameRepo(session).upsert("g2", season=2025, week=2, home_team="A", away_team="C")
    session.commit()

    repo = StatsRepo(session)
    repo.upsert("p1", "g1", pass_yards=300, source="test")
    repo.upsert("p1", "g2", pass_yards=250, source="test")
    session.commit()

    all_games = repo.get_player_games("p1", season=2025)
    assert len(all_games) == 2

    recent = repo.get_recent_games("p1", limit=1)
    assert len(recent) == 1
    assert recent[0].pass_yards == 250  # Week 2 is more recent


def test_prop_line_add_and_query(session, sample_player, sample_game):
    repo = PropLineRepo(session)
    repo.add(
        player_id=sample_player.player_id,
        game_id=sample_game.game_id,
        market="pass_yards",
        line_value=275.5,
    )
    session.commit()

    props = repo.get_for_player_game(sample_player.player_id, sample_game.game_id)
    assert len(props) == 1
    assert props[0].market == "pass_yards"


def test_prediction_add_and_get_latest(session, sample_player, sample_game):
    repo = PredictionRepo(session)
    repo.add(
        player_id=sample_player.player_id,
        game_id=sample_game.game_id,
        predicted_stats={"pass_yards": {"expected": 280}},
        confidence_score=72.0,
    )
    session.commit()

    latest = repo.get_latest(sample_player.player_id, sample_game.game_id)
    assert latest is not None
    assert latest.confidence_score == 72.0


def test_defense_profile_upsert_and_get_latest(session):
    repo = DefenseProfileRepo(session)
    repo.upsert("BUF", 2025, 5, source="nflverse", pass_yards_allowed=210.0)
    repo.upsert("BUF", 2025, 9, source="nflverse", pass_yards_allowed=225.5)
    session.commit()

    latest = repo.get_latest("BUF", 2025)
    assert latest is not None
    assert latest.week_through == 9
    assert latest.pass_yards_allowed == 225.5
