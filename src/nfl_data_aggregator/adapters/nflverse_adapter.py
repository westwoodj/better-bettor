"""Adapter wrapping nfl_data_py with lazy import and graceful degradation.

nfl_data_py provides access to nflverse data (player stats, rosters, schedules).
If the library isn't installed, methods return empty results instead of crashing.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_nfl_data_py = None
_import_attempted = False


def _ensure_import():
    """Lazily import nfl_data_py; return True if available."""
    global _nfl_data_py, _import_attempted
    if _import_attempted:
        return _nfl_data_py is not None
    _import_attempted = True
    try:
        import nfl_data_py as nfl
        _nfl_data_py = nfl
        return True
    except ImportError:
        logger.warning("nfl_data_py not installed; nflverse adapter will return empty results")
        return False


class NflverseAdapter:
    """Wraps nfl_data_py with graceful degradation and schema normalization."""

    def import_weekly_data(self, seasons: list[int], columns: list[str] | None = None) -> list[dict]:
        """Import weekly player stats from nflverse.

        Returns list of dicts normalized to our schema.
        """
        if not _ensure_import():
            return []
        try:
            df = _nfl_data_py.import_weekly_data(seasons, columns=columns)
            return self._normalize_weekly(df)
        except Exception:
            logger.exception("Failed to import weekly data from nflverse")
            return []

    def import_rosters(self, seasons: list[int]) -> list[dict]:
        """Import player rosters from nflverse."""
        if not _ensure_import():
            return []
        try:
            df = _nfl_data_py.import_rosters(seasons)
            return self._normalize_rosters(df)
        except Exception:
            logger.exception("Failed to import rosters from nflverse")
            return []

    def import_schedule(self, seasons: list[int]) -> list[dict]:
        """Import game schedules from nflverse."""
        if not _ensure_import():
            return []
        try:
            df = _nfl_data_py.import_schedules(seasons)
            return self._normalize_schedule(df)
        except Exception:
            logger.exception("Failed to import schedule from nflverse")
            return []

    def get_player_weekly_stats(self, season: int, week: Optional[int] = None) -> list[dict]:
        """Get player weekly stats for a specific season, optionally filtered by week."""
        if not _ensure_import():
            return []
        try:
            df = _nfl_data_py.import_weekly_data([season])
            if week is not None:
                df = df[df["week"] == week]
            return self._normalize_weekly(df)
        except Exception:
            logger.exception("Failed to get weekly stats from nflverse")
            return []

    def _normalize_weekly(self, df) -> list[dict]:
        """Normalize nflverse weekly data DataFrame to our schema."""
        records = []
        col_map = {
            "player_id": "nflverse_id",
            "player_name": "name",
            "player_display_name": "name",
            "recent_team": "team",
            "position": "position",
            "week": "week",
            "season": "season",
            "completions": "pass_completions",
            "attempts": "pass_attempts",
            "passing_yards": "pass_yards",
            "passing_tds": "pass_tds",
            "interceptions": "interceptions",
            "carries": "rush_attempts",
            "rushing_yards": "rush_yards",
            "rushing_tds": "rush_tds",
            "receptions": "receptions",
            "targets": "targets",
            "receiving_yards": "receiving_yards",
            "receiving_tds": "receiving_tds",
            "fantasy_points": "fantasy_points",
            "fantasy_points_ppr": "fantasy_points",
        }

        try:
            for _, row in df.iterrows():
                record = {"source": "nflverse"}
                for nfl_col, our_col in col_map.items():
                    if nfl_col in df.columns:
                        val = row.get(nfl_col)
                        if hasattr(val, "item"):
                            val = val.item()
                        if val != val:  # NaN check
                            val = None
                        record[our_col] = val
                records.append(record)
        except Exception:
            logger.exception("Error normalizing weekly data")
        return records

    def _normalize_rosters(self, df) -> list[dict]:
        """Normalize nflverse roster DataFrame to player dicts."""
        records = []
        try:
            for _, row in df.iterrows():
                pos = row.get("position", "")
                if pos not in ("QB", "RB", "WR", "TE", "K"):
                    continue
                record = {
                    "nflverse_id": row.get("player_id") or row.get("gsis_id"),
                    "name": row.get("player_name") or row.get("full_name", ""),
                    "team": row.get("team", ""),
                    "position": pos,
                    "status": row.get("status"),
                    "height": row.get("height"),
                    "weight": _safe_int(row.get("weight")),
                    "experience": _safe_int(row.get("years_exp")),
                }
                records.append(record)
        except Exception:
            logger.exception("Error normalizing roster data")
        return records

    def _normalize_schedule(self, df) -> list[dict]:
        """Normalize nflverse schedule DataFrame to game dicts."""
        records = []
        try:
            for _, row in df.iterrows():
                record = {
                    "game_id": row.get("game_id", ""),
                    "season": _safe_int(row.get("season")),
                    "week": _safe_int(row.get("week")),
                    "game_type": row.get("game_type", ""),
                    "home_team": row.get("home_team", ""),
                    "away_team": row.get("away_team", ""),
                    "kickoff_time": row.get("gameday"),
                    "venue": row.get("stadium"),
                    "weather_conditions": _build_weather(row),
                    "final_score": _build_score(row),
                }
                records.append(record)
        except Exception:
            logger.exception("Error normalizing schedule data")
        return records


def _safe_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        v = int(val)
        return v
    except (ValueError, TypeError):
        return None


def _build_weather(row) -> Optional[dict]:
    temp = row.get("temp")
    wind = row.get("wind")
    if temp is None and wind is None:
        return None
    weather = {}
    if temp is not None and temp == temp:  # NaN check
        weather["temp"] = temp
    if wind is not None and wind == wind:
        weather["wind"] = wind
    return weather or None


def _build_score(row) -> Optional[str]:
    home = row.get("home_score")
    away = row.get("away_score")
    if home is not None and away is not None:
        try:
            return f"{int(home)}-{int(away)}"
        except (ValueError, TypeError):
            pass
    return None
