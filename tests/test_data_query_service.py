"""Tests for MCP database queries and bounded ESPN refresh behavior."""

import pytest
from sqlalchemy import func, select

from nfl_data_aggregator.db.repository import GameRepo, PlayerRepo, StatsRepo
from nfl_data_aggregator.db.sa_models import Game
from nfl_data_aggregator.services.data_query_service import DataQueryError, DataQueryService


def _summary(game_id="401000001", week=1, player_id="p1"):
    return {
        "header": {
            "id": game_id,
            "date": "2026-09-13T17:00:00Z",
            "season": {"year": 2026, "type": 2},
            "week": {"number": week},
            "competitions": [{
                "status": {"type": {"completed": True}},
                "competitors": [
                    {"homeAway": "away", "score": "17", "team": {"abbreviation": "BUF"}},
                    {"homeAway": "home", "score": "24", "team": {"abbreviation": "KC"}},
                ],
                "venue": {
                    "fullName": "Arrowhead Stadium",
                    "address": {"city": "Kansas City", "state": "MO", "country": "USA"},
                },
                "weather": {"temperature": 72, "windSpeed": 8, "displayValue": "Clear"},
            }],
        },
        "boxscore": {"players": [{
            "team": {"abbreviation": "KC"},
            "statistics": [{
                "name": "passing",
                "labels": ["C/ATT", "YDS", "TD", "INT"],
                "athletes": [{
                    "athlete": {
                        "id": player_id,
                        "displayName": "Test Quarterback",
                        "position": {"abbreviation": "QB"},
                    },
                    "stats": ["20/30", "250", "2", "1"],
                }],
            }],
        }]},
    }


class PlayerRefreshClient:
    def __init__(self, fail_second=False):
        self.calls = []
        self.fail_second = fail_second

    def player_gamelog(self, athlete_id, season, force=False):
        self.calls.append(("gamelog", athlete_id, season, force))
        return {"events": [{"id": "401000001"}, {"id": "401000002"}]}

    def event_summary(self, game_id, force=False):
        self.calls.append(("summary", game_id, force))
        if self.fail_second and game_id == "401000002":
            raise RuntimeError("upstream unavailable")
        return _summary(game_id, 1 if game_id.endswith("1") else 2)


def test_cached_player_performances_do_not_call_network(session):
    player = PlayerRepo(session).upsert("p1", espn_id="99", name="Test", team="KC", position="QB")
    game = GameRepo(session).upsert(
        "g1", season=2026, week=1, home_team="KC", away_team="BUF"
    )
    StatsRepo(session).upsert(player.player_id, game.game_id, pass_yards=250, source="test")
    session.commit()

    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError(f"unexpected network access: {name}")

    result = DataQueryService(session, NoNetwork()).get_player_performances("p1")
    assert result.performances[0].pass_yards == 250
    assert result.refresh.refreshed is False


def test_force_player_season_propagates_and_persists(session):
    PlayerRepo(session).upsert("p1", espn_id="99", name="Test", team="KC", position="QB")
    session.commit()
    client = PlayerRefreshClient()

    result = DataQueryService(session, client).get_player_performances(
        "p1", season=2026, force=True
    )

    assert len(result.performances) == 2
    assert result.refresh.refreshed is True
    assert client.calls[0] == ("gamelog", "99", 2026, True)
    assert all(call[-1] is True for call in client.calls)
    assert result.performances[0].week == 2


def test_force_player_season_rolls_back_partial_refresh(session):
    PlayerRepo(session).upsert("p1", espn_id="99", name="Test", team="KC", position="QB")
    session.commit()

    with pytest.raises(DataQueryError, match="ESPN refresh failed"):
        DataQueryService(session, PlayerRefreshClient(fail_second=True)).get_player_performances(
            "p1", season=2026, force=True
        )

    assert session.scalar(select(func.count()).select_from(Game)) == 0


class RosterClient:
    def __init__(self):
        self.calls = []

    def find_team_by_name(self, name):
        return {"id": "12", "abbreviation": "KC"}

    def roster(self, team_id, force=False):
        self.calls.append((team_id, force))
        return {
            "team": {"abbreviation": "KC"},
            "athletes": [{"items": [
                {"id": "qb1", "fullName": "Quarterback", "position": {"abbreviation": "QB"}},
                {"id": "lb1", "fullName": "Linebacker", "position": {"abbreviation": "LB"}},
            ]}],
        }


def test_roster_defaults_to_skill_positions_and_supports_full_scope(session):
    client = RosterClient()
    service = DataQueryService(session, client)
    skill = service.get_roster("chiefs", force=True)
    assert [player.position for player in skill.players] == ["QB"]
    assert client.calls == [("12", True)]

    full = service.get_roster("KC", include_all_positions=True, force=True)
    assert {player.position for player in full.players} == {"QB", "LB"}
    assert client.calls[-1] == ("12", True)


def test_roster_refresh_reconciles_only_requested_scope(session):
    PlayerRepo(session).upsert("old-qb", name="Old QB", team="KC", position="QB")
    PlayerRepo(session).upsert("old-lb", name="Old LB", team="KC", position="LB")
    session.commit()
    DataQueryService(session, RosterClient()).get_roster("KC", force=True)
    assert PlayerRepo(session).get("old-qb").team is None
    assert PlayerRepo(session).get("old-lb").team == "KC"


class WeekClient(PlayerRefreshClient):
    def scoreboard(self, dates=None, week=None, seasontype=None, force=False):
        self.calls.append(("scoreboard", dates, week, seasontype, force))
        summary = _summary("401000001", week)
        return {"events": [summary["header"]]}


def test_force_week_is_bounded_and_propagates_season(session):
    client = WeekClient()
    result = DataQueryService(session, client).list_games(2026, week=3, force=True)
    assert len(result.games) == 1
    assert ("scoreboard", "2026", 3, 2, True) in client.calls
    assert ("summary", "401000001", True) in client.calls


def test_force_week_requires_week(session):
    with pytest.raises(DataQueryError, match="week is required"):
        DataQueryService(session, WeekClient()).list_games(2026, force=True)


def test_cache_status_does_not_expose_credentials(session, sample_player):
    status = DataQueryService(session).get_cache_status()
    assert status.record_counts["players"] == 1
    assert status.database == {"dialect": "sqlite"}


def test_limit_validation(session):
    with pytest.raises(DataQueryError, match="between 1 and 100"):
        DataQueryService(session).search_players("test", limit=101)
