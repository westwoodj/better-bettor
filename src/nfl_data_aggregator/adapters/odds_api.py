from typing import List, Optional
import logging
from datetime import datetime, timezone
from ..models import Odds
from ..config.config import settings

logger = logging.getLogger(__name__)

# The Odds API base URL (v4)
ODDS_API_BASE = "https://api.the-odds-api.com/v4"


def _default_mock(matchup_id: str) -> List[Odds]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        Odds(
            provider="MockOdds",
            spread=-3.5,
            spread_favorite="Home",
            moneyline_home=-180.0,
            moneyline_away=150.0,
            total=44.5,
            last_updated=now,
        )
    ]


def _preferred_markets() -> List[str]:
    # Request a set of markets that cover spreads, totals, team totals and
    # player props. The Odds API exposes player props under player_props.
    return [
        "spreads",
        "totals",
        "team_totals",
        "alternate_spreads",
        "alternate_totals",
        "alternate_team_totals",
        "player_props",
        "h2h",
    ]


def _safe_get_first_event(data: list, matchup_id: str) -> Optional[dict]:
    if not isinstance(data, list) or len(data) == 0:
        return None
    # Try to find by explicit id first
    for ev in data:
        if ev.get("id") == matchup_id:
            return ev
    # fallback: return the first event
    return data[0]


def fetch_current_odds(matchup_id: str, sport_key: str = "americanfootball_nfl", regions: str = "us") -> List[Odds]:
    """Fetch current odds for a matchup from The Odds API.

    - If `settings.ODDS_API_KEY` is not set, this function returns a mocked list
      (keeps behavior friendly for development).
    - This function requests a conservative set of markets that includes
      player props (`player_props`) which will include player_pass*, player_rush*,
      player_reception*, player_anytime_td, player_sacks, player_solo_tackles,
      player_tackles_assists where available from the provider.

    Parameters
    - matchup_id: The event id you expect from The Odds API (if you have it).
                 If None or not matched, the first returned event will be used.
    - sport_key: The Odds API sport key (defaults to NFL key).
    - regions: Comma-separated region param for the Odds API (defaults to "us").

    Returns a list of `Odds` model instances (one per bookmaker/provider).
    """
    api_key = getattr(settings, "ODDS_API_KEY", None)
    if not api_key:
        logger.debug("No ODDS_API_KEY configured; returning mock odds for %s", matchup_id)
        return _default_mock(matchup_id)

    try:
        import requests
    except Exception:
        logger.exception("requests library is required for The Odds API adapter")
        return _default_mock(matchup_id)

    markets = ",".join(_preferred_markets())
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
    }

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning("The Odds API returned %s: %s", resp.status_code, resp.text)
            return _default_mock(matchup_id)
        data = resp.json()
    except Exception as exc:
        logger.exception("Error calling The Odds API: %s", exc)
        return _default_mock(matchup_id)

    event = _safe_get_first_event(data, matchup_id)
    if not event:
        logger.debug("No event found in The Odds API response for matchup_id=%s", matchup_id)
        return []

    home = event.get("home_team")
    away = event.get("away_team")
    last_updated = event.get("commence_time") or datetime.now(timezone.utc).isoformat()

    odds_list: List[Odds] = []
    for bookmaker in event.get("bookmakers", []):
        provider = bookmaker.get("title") or bookmaker.get("key")
        spread = None
        spread_favorite = None
        moneyline_home = None
        moneyline_away = None
        total = None
        player_props = []

        for market in bookmaker.get("markets", []):
            key = market.get("key", "")
            outcomes = market.get("outcomes", []) or []

            # Spreads
            if "spread" in key:
                for o in outcomes:
                    point = o.get("point")
                    if point is None:
                        continue
                    # Negative point typically indicates the favorite
                    if point < 0:
                        spread = abs(point)
                        spread_favorite = o.get("name")
                        break

            # Moneyline / h2h
            if key in ("h2h", "moneyline"):
                for o in outcomes:
                    name = o.get("name")
                    price = o.get("price")
                    if name == home:
                        moneyline_home = price
                    elif name == away:
                        moneyline_away = price

            # Totals
            if "total" in key or "totals" in key:
                # Try to find an Over outcome and take its point as the total
                for o in outcomes:
                    if o.get("name", "").lower().startswith("over"):
                        total = o.get("point")
                        break

            # Player props: match keys that start with the allowed prefixes
            player_prefixes = [
                "player_pass",
                "player_rush",
                "player_reception",
                "player_anytime_td",
                "player_sacks",
                "player_solo_tackles",
                "player_tackles_assists",
            ]
            # also accept generic 'player_props' market
            # Exclude specific undesired markets explicitly
            excluded_patterns = ("player_rush_reception_tds", "player_reception_tds")
            if key == "player_props" or (
                any(key.startswith(p) for p in player_prefixes)
                and not any(pat in key for pat in excluded_patterns)
                and not key.endswith("_tds")
            ):
                for o in outcomes:
                    # o may contain participant/player name under various fields
                    player_name = o.get("participant") or o.get("player") or o.get("name")
                    # Try to split name like 'Over 22.5 - Player X' or similar
                    if isinstance(player_name, str) and " - " in player_name:
                        parts = player_name.split(" - ")
                        # heuristic: last part likely player
                        player_name = parts[-1]

                    line = o.get("point")
                    direction = None
                    nm = o.get("name", "")
                    if isinstance(nm, str):
                        nm_low = nm.lower()
                        if nm_low.startswith("over"):
                            direction = "over"
                        elif nm_low.startswith("under"):
                            direction = "under"

                    price = o.get("price")

                    prop = {
                        "market_key": key,
                        "player_name": player_name,
                        "line": line,
                        "direction": direction,
                        "price": price,
                        "raw_name": o.get("name"),
                    }
                    player_props.append(prop)

        odds_obj = Odds(
            provider=provider,
            spread=spread,
            spread_favorite=spread_favorite,
            moneyline_home=moneyline_home,
            moneyline_away=moneyline_away,
            total=total,
            last_updated=last_updated,
            player_props=player_props if player_props else None,
        )
        odds_list.append(odds_obj)

    return odds_list


# For backward compatibility expose the same function name previously used
# by the scaffold (it previously returned a mock list). If you prefer to
# separate the real and mock flows, you can add a new function name.
