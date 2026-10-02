"""Tests for SQLAlchemy ORM models."""

import os, sys
from datetime import datetime, timezone
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.db.sa_models import (
    Base, Player, Game, PlayerGameStats, PropLine, Prediction, DefenseProfile,
    OddsEvent, OddsSnapshot, OddsLine,
)


def test_all_tables_created(engine):
    """Verify all expected tables are created."""
    tables = Base.metadata.tables.keys()
    expected = {
        "players", "games", "player_game_stats", "prop_lines", "predictions",
        "defense_profiles", "odds_events", "odds_snapshots", "odds_lines",
    }
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


def test_odds_snapshot_preserves_repeated_fetches(session):
    event = OddsEvent(
        event_id="event-1",
        sport_key="americanfootball_nfl",
        commence_time=datetime(2026, 9, 20, 17, 0, tzinfo=timezone.utc),
        home_team="Kansas City Chiefs",
        away_team="Buffalo Bills",
    )
    session.add(event)
    session.flush()
    first = OddsSnapshot(
        event_id=event.event_id,
        request_signature="same",
        requested_markets=["h2h"],
        outcome_count=1,
    )
    second = OddsSnapshot(
        event_id=event.event_id,
        request_signature="same",
        requested_markets=["h2h"],
        outcome_count=1,
    )
    session.add_all([first, second])
    session.flush()
    session.add_all([
        OddsLine(
            snapshot_id=first.id, bookmaker_key="book", market_key="h2h",
            outcome_name="Kansas City Chiefs", price=-110,
        ),
        OddsLine(
            snapshot_id=second.id, bookmaker_key="book", market_key="h2h",
            outcome_name="Kansas City Chiefs", price=-110,
        ),
    ])
    session.commit()
    assert first.id != second.id
    assert len(event.snapshots) == 2
