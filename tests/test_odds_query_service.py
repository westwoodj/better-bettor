"""Persistence, cache, history, and linking tests for sportsbook lines."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from nfl_data_aggregator.adapters.odds_api import OddsAPIError, OddsAPIResponse
from nfl_data_aggregator.db.repository import GameRepo, PlayerRepo
from nfl_data_aggregator.db.sa_models import OddsEvent, OddsLine, OddsSnapshot
from nfl_data_aggregator.services.odds_query_service import OddsQueryError, OddsQueryService


EVENT = {
    "id": "event-1",
    "sport_key": "americanfootball_nfl",
    "sport_title": "NFL",
    "commence_time": "2026-09-20T17:00:00Z",
    "home_team": "Kansas City Chiefs",
    "away_team": "Buffalo Bills",
}


def odds_payload():
    return {
        **EVENT,
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "markets": [
                {
                    "key": "h2h",
                    "last_update": "2026-09-20T12:00:00Z",
                    "outcomes": [
                        {"name": "Kansas City Chiefs", "price": -135},
                        {"name": "Buffalo Bills", "price": 115},
                    ],
                },
                {
                    "key": "player_pass_yds",
                    "last_update": "2026-09-20T12:01:00Z",
                    "outcomes": [
                        {"name": "Over", "description": "Patrick Mahomes", "price": -110, "point": 275.5},
                        {"name": "Under", "description": "Patrick Mahomes", "price": -110, "point": 275.5},
                    ],
                },
            ],
        }],
    }


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 20, 12, 5, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


class Client:
    def __init__(self):
        self.event_calls = []
        self.odds_calls = []
        self.fail_odds = False
        self.payload = odds_payload()

    def list_events(self, sport_key, **kwargs):
        self.event_calls.append((sport_key, kwargs))
        return OddsAPIResponse([EVENT])

    def get_event_odds(self, sport_key, event_id, **kwargs):
        self.odds_calls.append((sport_key, event_id, kwargs))
        if self.fail_odds:
            raise OddsAPIError("upstream unavailable")
        return OddsAPIResponse(
            self.payload,
            {"remaining": 90, "used": 10, "last": 2},
        )


class Teams:
    def find_team_by_name(self, name):
        values = {"Kansas City Chiefs": "KC", "Buffalo Bills": "BUF"}
        return {"abbreviation": values[name]} if name in values else None


def service(session, client=None, clock=None):
    return OddsQueryService(
        session,
        client or Client(),
        espn_client=Teams(),
        now=clock or Clock(),
    )


def test_fetch_persists_snapshot_lines_quota_and_links(session):
    GameRepo(session).upsert(
        "game-1",
        season=2026,
        week=3,
        home_team="KC",
        away_team="BUF",
        kickoff_time=datetime(2026, 9, 20, 17, 0),
    )
    PlayerRepo(session).upsert("p1", name="Patrick Mahomes", team="KC", position="QB")
    session.commit()
    client = Client()

    result = service(session, client).get_betting_lines(
        "americanfootball_nfl",
        "event-1",
        market_keys=["h2h", "player_pass_yds"],
    )

    assert result.event.game_id == "game-1"
    assert result.cache.refreshed is True
    assert result.snapshot.outcome_count == 4
    assert result.snapshot.quota.last == 2
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 1
    player_lines = list(session.scalars(
        select(OddsLine).where(OddsLine.market_key == "player_pass_yds")
    ))
    assert {line.player_id for line in player_lines} == {"p1"}


def test_fresh_cache_then_force_creates_distinct_snapshot(session):
    client = Client()
    query = service(session, client)
    first = query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["h2h"])
    cached = query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["h2h"])
    forced = query.get_betting_lines(
        "americanfootball_nfl", "event-1", market_keys=["h2h"], force=True
    )
    assert first.snapshot.snapshot_id == cached.snapshot.snapshot_id
    assert cached.cache.refreshed is False
    assert forced.snapshot.snapshot_id != first.snapshot.snapshot_id
    assert len(client.odds_calls) == 2


def test_request_signature_isolates_market_sets(session):
    client = Client()
    query = service(session, client)
    query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["h2h"])
    query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["totals"])
    assert len(client.odds_calls) == 2
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 2


def test_expired_refresh_failure_returns_stale_but_force_fails(session):
    client = Client()
    clock = Clock()
    query = service(session, client, clock)
    first = query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["h2h"])
    clock.value += timedelta(seconds=901)
    client.fail_odds = True
    stale = query.get_betting_lines("americanfootball_nfl", "event-1", market_keys=["h2h"])
    assert stale.snapshot.snapshot_id == first.snapshot.snapshot_id
    assert stale.cache.stale is True
    assert "returning stale snapshot" in stale.cache.warnings[0]
    with pytest.raises(OddsQueryError, match="Odds refresh failed"):
        query.get_betting_lines(
            "americanfootball_nfl", "event-1", market_keys=["h2h"], force=True
        )


def test_failed_initial_refresh_rolls_back_snapshot(session):
    client = Client()
    client.fail_odds = True
    with pytest.raises(OddsQueryError, match="Odds refresh failed"):
        service(session, client).get_betting_lines(
            "americanfootball_nfl", "event-1", market_keys=["h2h"]
        )
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(OddsLine)) == 0


def test_malformed_payload_rolls_back_partial_lines(session):
    client = Client()
    client.payload = odds_payload()
    client.payload["bookmakers"][0]["markets"].append({
        "key": "totals",
        "outcomes": [{"name": "Over", "price": "not-a-number", "point": 47.5}],
    })
    with pytest.raises(OddsQueryError, match="non-numeric odds"):
        service(session, client).get_betting_lines(
            "americanfootball_nfl", "event-1", market_keys=["h2h", "totals"]
        )
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(OddsLine)) == 0


def test_empty_success_is_stored(session):
    client = Client()
    client.payload = {**EVENT, "bookmakers": []}
    result = service(session, client).get_betting_lines(
        "americanfootball_nfl", "event-1", market_keys=["h2h"]
    )
    assert result.snapshot.outcome_count == 0
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 1


def test_history_is_database_only_and_filters_lines(session):
    client = Client()
    query = service(session, client)
    query.get_betting_lines(
        "americanfootball_nfl",
        "event-1",
        market_keys=["h2h", "player_pass_yds"],
    )
    calls = len(client.odds_calls)
    history = query.get_betting_line_history(
        "americanfootball_nfl",
        "event-1",
        market_keys=["player_pass_yds"],
        bookmaker_keys=["draftkings"],
        participant="mahomes",
    )
    assert len(client.odds_calls) == calls
    assert len(history.snapshots) == 1
    markets = history.snapshots[0].bookmakers[0].markets
    assert [market.market_key for market in markets] == ["player_pass_yds"]
    assert len(markets[0].outcomes) == 2


def test_ambiguous_player_name_is_not_linked(session):
    PlayerRepo(session).upsert("p1", name="Patrick Mahomes")
    PlayerRepo(session).upsert("p2", name="Patrick Mahomes")
    session.commit()
    service(session).get_betting_lines(
        "americanfootball_nfl", "event-1", market_keys=["player_pass_yds"]
    )
    ids = set(session.scalars(select(OddsLine.player_id)).all())
    assert ids == {None}


def test_ambiguous_local_game_is_not_linked(session):
    for game_id, hour in (("g1", 16), ("g2", 18)):
        GameRepo(session).upsert(
            game_id,
            season=2026,
            week=3,
            home_team="KC",
            away_team="BUF",
            kickoff_time=datetime(2026, 9, 20, hour, 0),
        )
    session.commit()
    result = service(session).list_events("americanfootball_nfl", force=True)
    assert result.events[0].game_id is None


def test_history_rejects_unknown_event_without_network(session):
    with pytest.raises(OddsQueryError, match="not found"):
        service(session).get_betting_line_history("basketball_nba", "missing")
