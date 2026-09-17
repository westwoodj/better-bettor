"""Adapter to extract flat stat dicts from ESPN API responses.

Uses the existing NFLClient to fetch data, then normalizes ESPN's nested
JSON into flat dictionaries suitable for database ingestion.
"""

import logging
import re
from typing import Any, Optional

from .espn_api import NFLClient

logger = logging.getLogger(__name__)

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

# Maps ESPN stat category display names to our column names
_PASSING_MAP = {
    "completions/passingAttempts": ("pass_completions", "pass_attempts"),
    "passingYards": "pass_yards",
    "YDS": "pass_yards",
    "passingTouchdowns": "pass_tds",
    "TD": "pass_tds",
    "interceptions": "interceptions",
    "INT": "interceptions",
    "QBRating": "passer_rating",
}

_RUSHING_MAP = {
    "rushingAttempts": "rush_attempts",
    "CAR": "rush_attempts",
    "rushingYards": "rush_yards",
    "YDS": "rush_yards",
    "rushingTouchdowns": "rush_tds",
    "TD": "rush_tds",
    "yardsPerRushAttempt": "yards_per_carry",
    "YPC": "yards_per_carry",
}

_RECEIVING_MAP = {
    "receptions": "receptions",
    "REC": "receptions",
    "receivingTargets": "targets",
    "receivingYards": "receiving_yards",
    "YDS": "receiving_yards",
    "receivingTouchdowns": "receiving_tds",
    "TD": "receiving_tds",
    "yardsPerReception": "yards_per_reception",
    "AVG": "yards_per_reception",
}

_FUMBLE_MAP = {
    "fumbles": "fumbles",
    "FUM": "fumbles",
    "fumblesLost": "fumbles_lost",
    "LOST": "fumbles_lost",
}


class ESPNStatsAdapter:
    """Extract players, games, and per-game stats from ESPN API data."""

    def __init__(self, client: NFLClient | None = None):
        self.client = client or NFLClient()

    def extract_games_from_scoreboard(self, scoreboard_data: dict) -> list[dict]:
        """Parse ESPN scoreboard response into flat game dicts."""
        games = []
        for event in scoreboard_data.get("events", []):
            game = self._extract_game(event, str(event.get("id", "")))
            if game:
                games.append(game)
        return games

    def extract_game_from_event_summary(self, summary_data: dict, game_id: str) -> Optional[dict]:
        """Parse game metadata from an ESPN event-summary response."""
        header = summary_data.get("header", {}) if isinstance(summary_data, dict) else {}
        competitions = header.get("competitions", []) if isinstance(header, dict) else []
        if not competitions:
            return None

        event = dict(header)
        event["id"] = str(header.get("id") or game_id)
        event["competitions"] = competitions
        if not event.get("season"):
            event["season"] = summary_data.get("season", {})
        if not event.get("week"):
            event["week"] = summary_data.get("week", {})
        game = self._extract_game(event, game_id)

        game_info = summary_data.get("gameInfo", {}) or {}
        if game and isinstance(game_info, dict):
            venue = game_info.get("venue") or {}
            if venue:
                game["venue"] = venue.get("fullName") or game.get("venue")
                game["venue_location"] = _venue_location(venue) or game.get("venue_location")
            weather = game_info.get("weather") or {}
            if weather:
                game["weather_conditions"] = _weather_conditions(weather)
        return game

    def extract_game_ids_from_gamelog(self, gamelog_data: dict) -> list[str]:
        """Return unique ESPN event IDs referenced by a player gamelog."""
        found: list[str] = []

        def add(value: Any) -> None:
            if value is None:
                return
            text = str(value)
            match = re.search(r"/events/(\d+)", text)
            event_id = match.group(1) if match else text
            if event_id.isdigit() and event_id not in found:
                found.append(event_id)

        def walk(value: Any, in_events: bool = False) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item, in_events=in_events)
                return
            if not isinstance(value, dict):
                return

            if value.get("eventId") is not None:
                add(value.get("eventId"))
            event = value.get("event")
            if isinstance(event, dict):
                add(event.get("id") or event.get("$ref"))
            elif event is not None:
                add(event)
            if in_events:
                add(value.get("id") or value.get("uid") or value.get("$ref"))

            for key, child in value.items():
                walk(child, in_events=(key == "events"))

        walk(gamelog_data)
        return found

    def extract_players_from_roster(
        self,
        roster_data: dict,
        team_abbr: str = "",
        *,
        include_all_positions: bool = False,
    ) -> list[dict]:
        """Parse ESPN roster data, defaulting to prediction-relevant positions."""
        players = []
        for group in roster_data.get("athletes", []):
            for athlete in group.get("items", []):
                pos = athlete.get("position", {}).get("abbreviation", "")
                if not include_all_positions and pos not in SKILL_POSITIONS:
                    continue
                status_info = athlete.get("status", {})
                players.append({
                    "player_id": str(athlete.get("id", "")),
                    "espn_id": str(athlete.get("id", "")),
                    "name": athlete.get("fullName", athlete.get("displayName", "")),
                    "team": team_abbr,
                    "position": pos,
                    "status": status_info.get("type") if isinstance(status_info, dict) else None,
                    "height": athlete.get("displayHeight"),
                    "weight": _safe_int(athlete.get("weight")),
                    "experience": _safe_int(athlete.get("experience", {}).get("years")) if isinstance(athlete.get("experience"), dict) else None,
                })
        return players

    def _extract_game(self, event: dict, fallback_game_id: str) -> Optional[dict]:
        competitions = event.get("competitions", []) or []
        if not competitions:
            return None
        competition = competitions[0] or {}
        competitors = competition.get("competitors", []) or []

        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if home is None or away is None:
            return None

        home_score = home.get("score")
        away_score = away.get("score")
        status = competition.get("status", {}).get("type", {}) or {}
        completed = status.get("completed")
        final_score = None
        if home_score is not None and away_score is not None and completed is not False:
            final_score = f"{home_score}-{away_score}"

        season_info = event.get("season", {}) or {}
        week_info = event.get("week", {}) or {}
        venue = competition.get("venue", {}) or {}
        weather = competition.get("weather", {}) or {}
        game_type = season_info.get("type")
        if isinstance(game_type, dict):
            game_type = game_type.get("type") or game_type.get("name")

        return {
            "game_id": str(event.get("id") or fallback_game_id),
            "season": _safe_int(season_info.get("year")) or 0,
            "week": _safe_int(week_info.get("number")) or 0,
            "game_type": str(game_type) if game_type is not None else None,
            "home_team": home.get("team", {}).get("abbreviation", ""),
            "away_team": away.get("team", {}).get("abbreviation", ""),
            "kickoff_time": event.get("date") or competition.get("date"),
            "venue": venue.get("fullName"),
            "venue_location": _venue_location(venue),
            "weather_conditions": _weather_conditions(weather),
            "final_score": final_score,
        }

    def extract_stats_from_event_summary(self, summary_data: dict, game_id: str) -> list[dict]:
        """Parse an ESPN event summary into per-player stat dicts."""
        stats_list = []
        boxscore = summary_data.get("boxscore", {})

        for team_players in boxscore.get("players", []):
            team_abbr = team_players.get("team", {}).get("abbreviation", "")
            for stat_group in team_players.get("statistics", []):
                category = stat_group.get("name", "").lower()
                stat_keys = stat_group.get("keys", [])
                stat_labels = stat_group.get("labels", [])

                for athlete_entry in stat_group.get("athletes", []):
                    athlete_info = athlete_entry.get("athlete", {})
                    player_id = str(athlete_info.get("id", ""))
                    position = athlete_info.get("position", {})
                    pos = position.get("abbreviation", "") if isinstance(position, dict) else ""

                    if pos not in SKILL_POSITIONS:
                        continue

                    values = athlete_entry.get("stats", [])
                    raw = dict(zip(stat_labels or stat_keys, values))

                    player_stats = {
                        "player_id": player_id,
                        "game_id": game_id,
                        "source": "espn",
                    }

                    if category == "passing":
                        player_stats.update(_parse_stat_group(raw, _PASSING_MAP))
                        # Handle compound "C/ATT" field
                        c_att = raw.get("C/ATT", raw.get("completions/passingAttempts"))
                        if c_att and "/" in str(c_att):
                            parts = str(c_att).split("/")
                            player_stats["pass_completions"] = _safe_int(parts[0])
                            player_stats["pass_attempts"] = _safe_int(parts[1])
                    elif category == "rushing":
                        player_stats.update(_parse_stat_group(raw, _RUSHING_MAP))
                    elif category == "receiving":
                        player_stats.update(_parse_stat_group(raw, _RECEIVING_MAP))
                    elif category == "fumbles":
                        player_stats.update(_parse_stat_group(raw, _FUMBLE_MAP))

                    stats_list.append(player_stats)

        # Merge stats for the same player across categories
        return _merge_player_stats(stats_list)

    def extract_player_info_from_summary(self, summary_data: dict) -> list[dict]:
        """Extract minimal player info from an event summary boxscore."""
        players = []
        seen = set()
        boxscore = summary_data.get("boxscore", {})

        for team_players in boxscore.get("players", []):
            team_abbr = team_players.get("team", {}).get("abbreviation", "")
            for stat_group in team_players.get("statistics", []):
                for athlete_entry in stat_group.get("athletes", []):
                    athlete_info = athlete_entry.get("athlete", {})
                    pid = str(athlete_info.get("id", ""))
                    if pid in seen:
                        continue
                    seen.add(pid)

                    position = athlete_info.get("position", {})
                    pos = position.get("abbreviation", "") if isinstance(position, dict) else ""
                    if pos not in SKILL_POSITIONS:
                        continue

                    players.append({
                        "player_id": pid,
                        "espn_id": pid,
                        "name": athlete_info.get("displayName", ""),
                        "team": team_abbr,
                        "position": pos,
                    })
        return players


def _parse_stat_group(raw: dict, mapping: dict) -> dict:
    """Map raw ESPN stat keys to our schema columns."""
    result = {}
    for espn_key, our_key in mapping.items():
        if espn_key in raw:
            val = raw[espn_key]
            if isinstance(our_key, tuple):
                # Compound field handled elsewhere
                continue
            if isinstance(val, str) and val.replace(".", "").replace("-", "").isdigit():
                result[our_key] = _safe_float(val)
            elif isinstance(val, (int, float)):
                result[our_key] = val
    return result


def _merge_player_stats(stats_list: list[dict]) -> list[dict]:
    """Merge multiple stat category entries for the same player+game."""
    merged = {}
    for entry in stats_list:
        key = (entry["player_id"], entry["game_id"])
        if key not in merged:
            merged[key] = dict(entry)
        else:
            for k, v in entry.items():
                if v is not None and k not in ("player_id", "game_id", "source"):
                    merged[key][k] = v
    return list(merged.values())


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _venue_location(venue: dict) -> Optional[dict]:
    address = venue.get("address", {}) if isinstance(venue, dict) else {}
    if not isinstance(address, dict):
        return None
    location = {
        "city": address.get("city"),
        "state": address.get("state"),
        "country": address.get("country"),
        "zip_code": address.get("zipCode"),
    }
    return {key: value for key, value in location.items() if value not in (None, "")} or None


def _weather_conditions(weather: dict) -> Optional[dict]:
    if not isinstance(weather, dict) or not weather:
        return None
    condition = weather.get("displayValue")
    if not condition and isinstance(weather.get("conditionId"), dict):
        condition = weather["conditionId"].get("displayValue")
    values = {
        "temp": weather.get("temperature"),
        "wind": weather.get("windSpeed"),
        "wind_direction": weather.get("windDirection"),
        "humidity": weather.get("humidity"),
        "condition": condition,
    }
    return {key: value for key, value in values.items() if value not in (None, "")} or None
