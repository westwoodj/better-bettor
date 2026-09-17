"""Tests for SQLAlchemy ORM models."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.db.sa_models import (
    Base, Player, Game, PlayerGameStats, PropLine, Prediction, DefenseProfile,
)


def test_all_tables_created(engine):
    """Verify all expected tables are created."""
    tables = Base.metadata.tables.keys()
    expected = {"players", "games", "player_game_stats", "prop_lines", "predictions", "defense_profiles"}
    assert expected.issubset(tables)


def test_player_insert(session):
    player = Player(player_id="p1", name="Test Player", team="KC", position="QB")
    session.add(player)
    session.commit()

    fetched = session.get(Player, "p1")
    assert fetched is not None
    assert fetched.name == "Test Player"
    assert fetched.team == "KC"


def test_game_insert(session):
    game = Game(game_id="g1", season=2025, week=1, home_team="KC", away_team="BUF")
    session.add(game)
    session.commit()

    fetched = session.get(Game, "g1")
    assert fetched is not None
    assert fetched.home_team == "KC"


def test_player_game_stats_composite_key(session):
    session.add(Player(player_id="p1", name="Player 1"))
    session.add(Game(game_id="g1", season=2025, week=1, home_team="A", away_team="B"))
    session.commit()

    stats = PlayerGameStats(
        player_id="p1", game_id="g1",
        pass_yards=300, pass_tds=3, source="test",
    )
    session.add(stats)
    session.commit()

    fetched = session.get(PlayerGameStats, ("p1", "g1"))
    assert fetched is not None
    assert fetched.pass_yards == 300
    assert fetched.pass_tds == 3


def test_prop_line_auto_increment(session):
    session.add(Player(player_id="p1", name="Player 1"))
    session.commit()

    prop = PropLine(player_id="p1", market="pass_yards", line_value=275.5)
    session.add(prop)
    session.commit()

    assert prop.id is not None
    assert prop.id > 0


def test_prediction_auto_increment(session):
    session.add(Player(player_id="p1", name="Player 1"))
    session.add(Game(game_id="g1", season=2025, week=1, home_team="A", away_team="B"))
    session.commit()

    pred = Prediction(
        player_id="p1", game_id="g1",
        predicted_stats={"pass_yards": {"expected": 280}},
        confidence_score=75.0,
    )
    session.add(pred)
    session.commit()
    assert pred.id is not None


def test_defense_profile_unique_constraint(session):
    import pytest

    dp1 = DefenseProfile(team="BUF", season=2025, week_through=5, source="nflverse")
    session.add(dp1)
    session.commit()

    dp2 = DefenseProfile(team="BUF", season=2025, week_through=5, source="nflverse")
    session.add(dp2)
    with pytest.raises(Exception):
        session.commit()


def test_relationships(session):
    """Verify ORM relationships between Player, Game, Stats."""
    player = Player(player_id="p1", name="Player 1")
    game = Game(game_id="g1", season=2025, week=1, home_team="A", away_team="B")
    session.add_all([player, game])
    session.commit()

    stats = PlayerGameStats(player_id="p1", game_id="g1", pass_yards=250)
    session.add(stats)
    session.commit()

    assert len(player.game_stats) == 1
    assert player.game_stats[0].pass_yards == 250
    assert len(game.game_stats) == 1
