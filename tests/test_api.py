"""Tests for the Gridiron Oracle REST API."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from nfl_data_aggregator.db.sa_models import Base, Player, Game, PlayerGameStats, Prediction
from nfl_data_aggregator.db.repository import PlayerRepo, GameRepo, StatsRepo, PredictionRepo
from nfl_data_aggregator.api.app import create_app, get_db


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sess = Session()
    yield sess
    sess.close()


@pytest.fixture
def client(session):
    """FastAPI TestClient with DB dependency overridden to use in-memory SQLite."""
    app = create_app()

    def _override_db():
        try:
            yield session
        finally:
            pass  # session cleanup handled by the session fixture

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_player(session):
    repo = PlayerRepo(session)
    player = repo.upsert(
        "12345",
        espn_id="12345",
        name="Patrick Mahomes",
        team="KC",
        position="QB",
        status="active",
    )
    session.commit()
    return player


@pytest.fixture
def sample_game(session):
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
def sample_stats(session, sample_player, sample_game):
    """Seed player game stats."""
    repo = StatsRepo(session)
    stats = repo.upsert(
        sample_player.player_id,
        sample_game.game_id,
        pass_completions=22,
        pass_attempts=35,
        pass_yards=280,
        pass_tds=3,
        interceptions=1,
        rush_attempts=4,
        rush_yards=25,
        rush_tds=0,
        fantasy_points=24.5,
        source="nflverse",
    )
    session.commit()
    return stats


@pytest.fixture
def sample_prediction_with_props(session, sample_player, sample_game):
    """Seed a prediction with recommended_props."""
    repo = PredictionRepo(session)
    pred = repo.add(
        player_id=sample_player.player_id,
        game_id=sample_game.game_id,
        predicted_stats={"pass_yards": {"floor": 220, "expected": 275, "ceiling": 330}},
        confidence_score=78.5,
        recommended_props=[
            {
                "market": "pass_yards",
                "line": 265.5,
                "predicted": 275,
                "edge": 9.5,
                "recommendation": "over",
                "sportsbook": "DraftKings",
            },
            {
                "market": "pass_tds",
                "line": 1.5,
                "predicted": 2.0,
                "edge": 0.5,
                "recommendation": "over",
                "sportsbook": "FanDuel",
            },
        ],
        model_version="phase1-v0.2.0",
    )
    session.commit()
    return pred


# --- Tests ---


class TestHealthCheck:
    def test_health_check_ok(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db_ok"] is True
        assert "version" in data

    def test_health_check_version(self, client):
        resp = client.get("/v1/health")
        assert resp.json()["version"] == "0.2.0"


class TestPlayerStats:
    def test_get_player_stats(self, client, sample_player, sample_game, sample_stats):
        resp = client.get(f"/v1/players/{sample_player.player_id}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["player"]["player_id"] == "12345"
        assert data["player"]["name"] == "Patrick Mahomes"
        assert data["player"]["team"] == "KC"
        assert data["player"]["position"] == "QB"
        assert len(data["games"]) == 1
        game_row = data["games"][0]
        assert game_row["game_id"] == "401234567"
        assert game_row["pass_yards"] == 280
        assert game_row["pass_tds"] == 3
        assert game_row["opponent"] == "BUF"

    def test_get_player_stats_with_season_filter(self, client, sample_player, sample_game, sample_stats):
        resp = client.get(f"/v1/players/{sample_player.player_id}/stats?season=2025")
        assert resp.status_code == 200
        assert len(resp.json()["games"]) == 1

        resp = client.get(f"/v1/players/{sample_player.player_id}/stats?season=2024")
        assert resp.status_code == 200
        assert len(resp.json()["games"]) == 0

    def test_player_not_found(self, client):
        resp = client.get("/v1/players/nonexistent/stats")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestGameContext:
    def test_get_game_context(self, client, sample_game):
        resp = client.get(f"/v1/games/{sample_game.game_id}/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == "401234567"
        assert data["season"] == 2025
        assert data["week"] == 10
        assert data["home_team"] == "KC"
        assert data["away_team"] == "BUF"
        assert data["venue"] == "Arrowhead Stadium"
        assert data["weather_conditions"]["temp"] == 45

    def test_game_not_found(self, client):
        resp = client.get("/v1/games/nonexistent/context")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_game_context_with_defense_profiles(self, client, session, sample_game):
        from nfl_data_aggregator.db.repository import DefenseProfileRepo

        repo = DefenseProfileRepo(session)
        repo.upsert(
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

        resp = client.get(f"/v1/games/{sample_game.game_id}/context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["away_defense"]["team"] == "BUF"
        assert data["away_defense"]["pass_yards_allowed"] == 225.5
        assert data["home_defense"] is None


class TestPropRecommendations:
    def test_get_all_recommendations(self, client, sample_prediction_with_props):
        resp = client.get("/v1/props/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) == 2
        markets = {r["market"] for r in data["recommendations"]}
        assert "pass_yards" in markets
        assert "pass_tds" in markets

    def test_filter_by_game_id(self, client, sample_prediction_with_props):
        resp = client.get("/v1/props/recommendations?game_id=401234567")
        assert resp.status_code == 200
        assert len(resp.json()["recommendations"]) == 2

        resp = client.get("/v1/props/recommendations?game_id=nonexistent")
        assert resp.status_code == 200
        assert len(resp.json()["recommendations"]) == 0

    def test_filter_by_min_edge(self, client, sample_prediction_with_props):
        resp = client.get("/v1/props/recommendations?min_edge=5.0")
        assert resp.status_code == 200
        recs = resp.json()["recommendations"]
        assert len(recs) == 1
        assert recs[0]["market"] == "pass_yards"

    def test_filter_by_sportsbook(self, client, sample_prediction_with_props):
        resp = client.get("/v1/props/recommendations?sportsbook=FanDuel")
        assert resp.status_code == 200
        recs = resp.json()["recommendations"]
        assert len(recs) == 1
        assert recs[0]["sportsbook"] == "FanDuel"

    def test_get_player_props(self, client, sample_player, sample_prediction_with_props):
        resp = client.get(f"/v1/props/recommendations/{sample_player.player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) == 2
        for rec in data["recommendations"]:
            assert rec["player_id"] == sample_player.player_id
            assert rec["player_name"] == "Patrick Mahomes"

    def test_player_props_not_found(self, client):
        resp = client.get("/v1/props/recommendations/nonexistent")
        assert resp.status_code == 404


# --- Lookup / Search Endpoints ---


class TestTeamSearch:
    def test_search_by_abbreviation(self, client):
        resp = client.get("/v1/teams/search?q=ARI")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["abbreviation"] == "ARI"

    def test_search_by_full_name(self, client):
        resp = client.get("/v1/teams/search?q=Arizona Cardinals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["displayName"] == "Arizona Cardinals"

    def test_search_by_city(self, client):
        resp = client.get("/v1/teams/search?q=Arizona")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_by_nickname(self, client):
        resp = client.get("/v1/teams/search?q=Cardinals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_partial_match(self, client):
        resp = client.get("/v1/teams/search?q=eagle")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_no_results(self, client):
        resp = client.get("/v1/teams/search?q=zzzznotateam")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 0

    def test_search_case_insensitive(self, client):
        resp = client.get("/v1/teams/search?q=chiefs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1


class TestRoster:
    def test_roster_from_db(self, client, sample_player):
        resp = client.get("/v1/teams/KC/roster")
        assert resp.status_code == 200
        data = resp.json()
        assert data["team"] == "KC"
        assert len(data["players"]) >= 1
        assert data["players"][0]["name"] == "Patrick Mahomes"

    def test_roster_empty_team_not_in_db_or_espn(self, client):
        resp = client.get("/v1/teams/ZZZ/roster")
        assert resp.status_code == 404

    def test_roster_case_insensitive_team(self, client, sample_player):
        resp = client.get("/v1/teams/kc/roster")
        assert resp.status_code == 200
        data = resp.json()
        assert data["team"] == "KC"
        assert len(data["players"]) >= 1


class TestPlayerSearch:
    def test_search_exact_match(self, client, sample_player):
        resp = client.get("/v1/players/search?q=Patrick Mahomes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["name"] == "Patrick Mahomes"

    def test_search_fuzzy_match(self, client, sample_player):
        resp = client.get("/v1/players/search?q=mahomes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["player_id"] == "12345"

    def test_search_no_results(self, client):
        resp = client.get("/v1/players/search?q=zzzznotaplayer")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 0

    def test_search_with_team_filter(self, client, sample_player):
        resp = client.get("/v1/players/search?q=mahomes&team=KC")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

        resp = client.get("/v1/players/search?q=mahomes&team=BUF")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 0

    def test_search_multiple_players(self, client, session):
        from nfl_data_aggregator.db.repository import PlayerRepo

        repo = PlayerRepo(session)
        repo.upsert("99991", espn_id="99991", name="Josh Allen", team="BUF", position="QB")
        repo.upsert("99992", espn_id="99992", name="Josh Jacobs", team="GB", position="RB")
        session.commit()

        resp = client.get("/v1/players/search?q=Josh")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 2


class TestGameSearch:
    def test_search_by_team_and_season(self, client, sample_game):
        resp = client.get("/v1/games/search?team=KC&season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["results"][0]["game_id"] == "401234567"

    def test_search_by_week(self, client, sample_game):
        resp = client.get("/v1/games/search?season=2025&week=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_by_team_only(self, client, sample_game):
        resp = client.get("/v1/games/search?team=BUF")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_no_results(self, client, sample_game):
        resp = client.get("/v1/games/search?team=ZZZ&season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 0

    def test_search_missing_params(self, client):
        resp = client.get("/v1/games/search")
        assert resp.status_code == 400
        assert "at least one" in resp.json()["detail"].lower()

    def test_search_by_season_only(self, client, sample_game):
        resp = client.get("/v1/games/search?season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1

    def test_search_team_case_insensitive(self, client, sample_game):
        resp = client.get("/v1/games/search?team=kc&season=2025")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) >= 1
