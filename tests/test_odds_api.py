"""Unit tests for The Odds API v4 HTTP client."""

import pytest

from nfl_data_aggregator.adapters.odds_api import (
    NFL_DEFAULT_MARKETS,
    OddsAPIClient,
    OddsAPIError,
    default_markets,
)


class Response:
    def __init__(self, payload, status_code=200, headers=None, text=""):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class HTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        return self.response


def test_event_odds_request_and_quota_headers():
    http = HTTP(Response(
        {"id": "e1", "bookmakers": []},
        headers={"x-requests-remaining": "99", "x-requests-used": "1", "x-requests-last": "3"},
    ))
    client = OddsAPIClient("secret", session=http)
    result = client.get_event_odds(
        "americanfootball_nfl", "e1", markets=["totals", "h2h"], regions=["us"]
    )
    url, params, timeout = http.calls[0]
    assert url.endswith("/sports/americanfootball_nfl/events/e1/odds")
    assert params["markets"] == "h2h,totals"
    assert params["regions"] == "us"
    assert params["oddsFormat"] == "american"
    assert params["apiKey"] == "secret"
    assert result.quota == {"remaining": 99, "used": 1, "last": 3}


def test_events_request_supports_filters():
    http = HTTP(Response([]))
    OddsAPIClient("secret", session=http).list_events(
        "basketball_nba",
        commence_time_from="2026-01-01T00:00:00Z",
        event_ids=["b", "a"],
    )
    _, params, _ = http.calls[0]
    assert params["eventIds"] == "a,b"
    assert params["commenceTimeFrom"] == "2026-01-01T00:00:00Z"


def test_missing_key_and_http_and_json_failures():
    with pytest.raises(OddsAPIError, match="ODDS_API_KEY"):
        OddsAPIClient("", session=HTTP(Response([]))).list_events("basketball_nba")
    with pytest.raises(OddsAPIError, match="HTTP 429"):
        OddsAPIClient("key", session=HTTP(Response({"message": "quota"}, 429))).list_events(
            "basketball_nba"
        )
    with pytest.raises(OddsAPIError, match="invalid JSON"):
        OddsAPIClient("key", session=HTTP(Response(ValueError("bad")))).list_events(
            "basketball_nba"
        )


def test_regions_and_bookmakers_are_mutually_exclusive():
    with pytest.raises(OddsAPIError, match="mutually exclusive"):
        OddsAPIClient("key", session=HTTP(Response({}))).get_event_odds(
            "basketball_nba",
            "e1",
            markets=["h2h"],
            regions=["us"],
            bookmakers=["fanduel"],
        )


def test_default_market_bundles_are_bounded():
    assert default_markets("basketball_nba") == ["h2h", "spreads", "totals"]
    assert "player_pass_attempts" in NFL_DEFAULT_MARKETS
    assert "player_anytime_td" in NFL_DEFAULT_MARKETS
    assert not any(key.endswith("_alternate") for key in NFL_DEFAULT_MARKETS)
    assert "player_sacks" not in NFL_DEFAULT_MARKETS

