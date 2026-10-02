"""HTTP client and market definitions for The Odds API v4."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import requests

from ..config.config import settings

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

CORE_MARKETS = ("h2h", "spreads", "totals")
NFL_DEFAULT_MARKETS = CORE_MARKETS + (
    "team_totals",
    "player_pass_attempts",
    "player_pass_completions",
    "player_pass_interceptions",
    "player_pass_longest_completion",
    "player_pass_rush_yds",
    "player_pass_rush_reception_tds",
    "player_pass_rush_reception_yds",
    "player_pass_tds",
    "player_pass_yds",
    "player_pass_yds_q1",
    "player_receptions",
    "player_reception_longest",
    "player_reception_tds",
    "player_reception_yds",
    "player_rush_attempts",
    "player_rush_longest",
    "player_rush_reception_tds",
    "player_rush_reception_yds",
    "player_rush_tds",
    "player_rush_yds",
    "player_tds_over",
    "player_tds",
    "player_1st_td",
    "player_anytime_td",
    "player_last_td",
)


class OddsAPIError(RuntimeError):
    """An actionable failure returned by or while calling The Odds API."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OddsAPIResponse:
    data: Any
    quota: dict[str, int | None] = field(default_factory=dict)


def default_markets(sport_key: str) -> list[str]:
    """Return the bounded default market bundle for a sport."""
    if sport_key == "americanfootball_nfl":
        return list(NFL_DEFAULT_MARKETS)
    return list(CORE_MARKETS)


def normalize_values(values: Iterable[str] | str | None) -> list[str]:
    """Normalize comma-separated or iterable request values."""
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    return sorted({str(value).strip().lower() for value in values if str(value).strip()})


class OddsAPIClient:
    """Small injectable synchronous client for The Odds API v4."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: Any | None = None,
        base_url: str = ODDS_API_BASE,
        timeout: float = 10.0,
    ):
        self.api_key = api_key if api_key is not None else settings.ODDS_API_KEY
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_events(
        self,
        sport_key: str,
        *,
        commence_time_from: str | None = None,
        commence_time_to: str | None = None,
        event_ids: Iterable[str] | str | None = None,
    ) -> OddsAPIResponse:
        params: dict[str, Any] = {"dateFormat": "iso"}
        if commence_time_from:
            params["commenceTimeFrom"] = commence_time_from
        if commence_time_to:
            params["commenceTimeTo"] = commence_time_to
        if isinstance(event_ids, str):
            event_ids = event_ids.split(",")
        ids = sorted({str(value).strip() for value in (event_ids or []) if str(value).strip()})
        if ids:
            params["eventIds"] = ",".join(ids)
        return self._get(f"/sports/{sport_key}/events", params)

    def get_event_odds(
        self,
        sport_key: str,
        event_id: str,
        *,
        markets: Iterable[str] | str,
        regions: Iterable[str] | str | None = None,
        bookmakers: Iterable[str] | str | None = None,
    ) -> OddsAPIResponse:
        region_values = normalize_values(regions)
        bookmaker_values = normalize_values(bookmakers)
        if region_values and bookmaker_values:
            raise OddsAPIError("regions and bookmakers are mutually exclusive")
        market_values = normalize_values(markets)
        if not market_values:
            raise OddsAPIError("at least one market key is required")

        params: dict[str, Any] = {
            "markets": ",".join(market_values),
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if bookmaker_values:
            params["bookmakers"] = ",".join(bookmaker_values)
        else:
            params["regions"] = ",".join(region_values or normalize_values(settings.ODDS_API_REGIONS))
        return self._get(f"/sports/{sport_key}/events/{event_id}/odds", params)

    def _get(self, path: str, params: dict[str, Any]) -> OddsAPIResponse:
        if not self.api_key:
            raise OddsAPIError("ODDS_API_KEY is not configured")
        request_params = dict(params)
        request_params["apiKey"] = self.api_key
        try:
            response = self.session.get(
                f"{self.base_url}{path}", params=request_params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise OddsAPIError(f"The Odds API request failed: {exc}") from exc
        except Exception as exc:
            raise OddsAPIError(f"The Odds API request failed: {exc}") from exc

        if response.status_code != 200:
            detail = _response_detail(response)
            raise OddsAPIError(
                f"The Odds API returned HTTP {response.status_code}: {detail}",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except Exception as exc:
            raise OddsAPIError("The Odds API returned invalid JSON") from exc
        return OddsAPIResponse(data=data, quota=_quota_headers(response.headers))


def _quota_headers(headers: Any) -> dict[str, int | None]:
    return {
        "remaining": _optional_int(headers.get("x-requests-remaining")),
        "used": _optional_int(headers.get("x-requests-used")),
        "last": _optional_int(headers.get("x-requests-last")),
    }


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _response_detail(response: Any) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or payload)[:300]
    except Exception:
        pass
    return str(getattr(response, "text", "upstream error"))[:300]
