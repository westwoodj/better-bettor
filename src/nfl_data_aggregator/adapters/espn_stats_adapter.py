"""Adapter to extract flat stat dicts from ESPN API responses.

Uses the existing NFLClient to fetch data, then normalizes ESPN's nested
JSON into flat dictionaries suitable for database ingestion.
"""

import logging
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
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            home_team = away_team = None
            final_score = None
            for comp in competitors:
                abbr = comp.get("team", {}).get("abbreviation", "")
                if comp.get("homeAway") == "home":
                    home_team = abbr
                else:
                    away_team = abbr

            # Build score string
            scores = []
            for comp in competitors:
                scores.append(comp.get("score", "0"))
            if len(scores) == 2:
                final_score = f"{scores[0]}-{scores[1]}"

            season_info = event.get("season", {})
            game = {
                "game_id": str(event.get("id", "")),
                "season": season_info.get("year", 0),
                "week": event.get("week", {}).get("number", 0) if isinstance(event.get("week"), dict) else 0,
                "game_type": season_info.get("type", ""),
                "home_team": home_team or "",
                "away_team": away_team or "",
                "kickoff_time": event.get("date"),
                "venue": competition.get("venue", {}).get("fullName") if competition.get("venue") else None,
                "final_score": final_score,
            }
            games.append(game)
        return games

    def extract_players_from_roster(self, roster_data: dict, team_abbr: str = "") -> list[dict]:
        """Parse ESPN roster response into flat player dicts, filtered to skill positions."""
        players = []
        for group in roster_data.get("athletes", []):
            for athlete in group.get("items", []):
                pos = athlete.get("position", {}).get("abbreviation", "")
                if pos not in SKILL_POSITIONS:
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
