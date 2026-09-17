"""Shared test fixtures for Gridiron Oracle tests."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nfl_data_aggregator.db.sa_models import Base, Player, Game, PlayerGameStats, PropLine, DefenseProfile
from nfl_data_aggregator.db.repository import PlayerRepo, GameRepo, StatsRepo, PropLineRepo, DefenseProfileRepo


@pytest.fixture
def engine():
    """Create an in-memory SQLite engine with all tables."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    """Create a session bound to the in-memory engine."""
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def sample_player(session):
    """Insert a sample QB and return the Player object."""
    repo = PlayerRepo(session)
    player = repo.upsert(
        "12345",
        espn_id="12345",
        name="Patrick Mahomes",
        team="KC",
        position="QB",
        status="active",
        experience=7,
    )
    session.commit()
    return player


@pytest.fixture
def sample_game(session):
    """Insert a sample upcoming game and return the Game object."""
    repo = GameRepo(session)
    game = repo.upsert(
        "401234567",
        season=2025,
        week=10,
        game_type="regular",
        home_team="KC",
        away_team="BUF",
        venue="Arrowhead Stadium",
        weather_conditions={"temp": 45, "wind": 12},
    )
    session.commit()
    return game


@pytest.fixture
def sample_games_8_weeks(session, sample_player):
    """Insert 8 weeks of games and stats for the sample player."""
    game_repo = GameRepo(session)
    stats_repo = StatsRepo(session)
    opponents = ["DET", "CIN", "ATL", "NO", "SF", "DEN", "LV", "LAC"]
    games = []
    for i, opp in enumerate(opponents, start=1):
        game = game_repo.upsert(
            f"game_wk{i}",
            season=2025,
            week=i,
            game_type="regular",
            home_team="KC" if i % 2 == 0 else opp,
            away_team=opp if i % 2 == 0 else "KC",
            venue="Arrowhead Stadium" if i % 2 == 0 else f"{opp} Stadium",
        )
        games.append(game)
        stats_repo.upsert(
            sample_player.player_id,
            game.game_id,
            pass_completions=20 + i,
            pass_attempts=30 + i,
            pass_yards=240 + i * 10,
            pass_tds=2 + (i % 3),
            interceptions=i % 2,
            rush_attempts=3 + (i % 4),
            rush_yards=15 + i * 3,
            rush_tds=i % 3,
            fantasy_points=18.0 + i * 1.5,
            source="nflverse",
        )
    session.commit()
    return games


@pytest.fixture
def sample_defense_profile(session):
    """Insert a defense profile for BUF."""
    repo = DefenseProfileRepo(session)
    profile = repo.upsert(
        team="BUF",
        season=2025,
        week_through=9,
        source="nflverse",
        pass_yards_allowed=225.5,
        rush_yards_allowed=98.3,
        points_allowed=19.8,
        pressure_rate=0.32,
    )
    session.commit()
    return profile


@pytest.fixture
def sample_prop_lines(session, sample_player, sample_game):
    """Insert sample prop lines for the player and game."""
    repo = PropLineRepo(session)
    props = [
        repo.add(
            player_id=sample_player.player_id,
            game_id=sample_game.game_id,
            market="pass_yards",
            line_value=275.5,
            over_odds=-110,
            under_odds=-110,
            sportsbook="DraftKings",
        ),
        repo.add(
            player_id=sample_player.player_id,
            game_id=sample_game.game_id,
            market="pass_tds",
            line_value=1.5,
            over_odds=-150,
            under_odds=120,
            sportsbook="FanDuel",
        ),
        repo.add(
            player_id=sample_player.player_id,
            game_id=sample_game.game_id,
            market="rush_yards",
            line_value=20.5,
            over_odds=-115,
            under_odds=-105,
            sportsbook="DraftKings",
        ),
    ]
    session.commit()
    return props
