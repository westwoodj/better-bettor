from typing import List, Optional, Any, Dict
from datetime import date
from dataclasses import dataclass, asdict, field
import json

# Provide a pydantic-compatible minimal fallback so the package can be used
# without installing pydantic during initial development or static checks.
try:
    from pydantic import BaseModel, Field
except Exception:
    BaseModel = object

    def Field(default: Any = None, **kwargs):
        return default

    # create a tiny BaseModel replacement with dict/json helpers if needed
    class SimpleBaseModel:
        def __init__(self, **data):
            for k, v in data.items():
                setattr(self, k, v)

        def dict(self):
            def _conv(v):
                if hasattr(v, "dict"):
                    return v.dict()
                if isinstance(v, list):
                    return [_conv(x) for x in v]
                return v

            return {k: _conv(v) for k, v in self.__dict__.items()}

        def json(self, **kwargs):
            import json as _json

            indent = kwargs.get("indent", None)
            return _json.dumps(self.dict(), default=str, ensure_ascii=False, indent=indent)

    BaseModel = SimpleBaseModel


class TeamStats(BaseModel):
    team_id: str
    team_name: str
    season: int
    wins: Optional[int] = None
    losses: Optional[int] = None
    points_for: Optional[float] = None
    points_against: Optional[float] = None
    offensive_rating: Optional[float] = None
    defensive_rating: Optional[float] = None


class PlayerStats(BaseModel):
    player_id: str
    player_name: str
    team_id: str
    position: Optional[str] = None
    season: int = None
    fantasy_points: Optional[float] = None
    snaps_pct: Optional[float] = None


class Matchup(BaseModel):
    matchup_id: str
    home_team: str
    away_team: str
    start_time: Optional[date] = None


class Odds(BaseModel):
    provider: str
    spread: Optional[float] = None
    spread_favorite: Optional[str] = None
    moneyline_home: Optional[float] = None
    moneyline_away: Optional[float] = None
    total: Optional[float] = None
    last_updated: Optional[str] = None
    player_props: Optional[List[dict]] = None


class FeatureSet(BaseModel):
    matchup: Matchup
    home_team_stats: TeamStats
    away_team_stats: TeamStats
    injured_players: Optional[List[PlayerStats]] = []
    market_odds: Optional[List[Odds]] = []


class Recommendation(BaseModel):
    matchup_id: str
    best_spread: Optional[float] = None
    best_spread_side: Optional[str] = None
    best_moneyline: Optional[str] = None
    best_total: Optional[float] = None
    player_props: Optional[List[dict]] = []
    rationale: Optional[str] = None


class RawModelResponse(BaseModel):
    raw_text: str
    parsed: Optional[Recommendation] = None


@dataclass
class Athlete:
    """Lightweight dataclass to represent an athlete in a depth chart.

    Fields:
    - first_name, last_name: names
    - position: position abbreviation or name
    - id: athlete id (string or int)
    - is_healthy: bool (best-effort)
    - slot: integer slot number
    - rank: integer rank within position/slot
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    position: Optional[str] = None
    id: Optional[str] = None
    is_healthy: Optional[bool] = None
    slot: Optional[int] = None
    rank: Optional[int] = None
    # store any additional metadata from the athlete resource
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Athlete":
        # Support both ESPN athlete object shapes and our internal shape
        first = None
        last = None
        aid = None
        is_healthy = None
        meta = {}

        # If object contains nested 'athlete' resource use that
        if "athlete" in d and isinstance(d["athlete"], dict):
            a = d["athlete"]
            meta.update({k: v for k, v in a.items() if k not in ("firstName", "lastName", "id")})
            first = a.get("firstName") or a.get("first_name") or a.get("preferredName")
            last = a.get("lastName") or a.get("last_name") or a.get("familyName")
            aid = a.get("id") or a.get("athleteId") or a.get("athlete_id")
            # attempt to infer health
            is_healthy = None
            if "injuryStatus" in a:
                is_healthy = not bool(a.get("injuryStatus"))
            elif "isInjured" in a:
                is_healthy = not bool(a.get("isInjured"))
            else:
                is_healthy = None
            # collect more known fields into meta
            for f in ("fullName", "displayName", "shortName", "jersey", "weight", "displayWeight", "height", "displayHeight", "dateOfBirth", "experience", "position", "team", "status"):
                if f in a:
                    meta[f] = a.get(f)
        else:
            # If top-level dict likely came from fetch_by_ref or already-resolved athlete
            meta.update({k: v for k, v in d.items() if k not in ("firstName", "lastName", "id", "slot", "rank", "position", "pos", "athlete")})
            first = d.get("firstName") or d.get("first_name") or d.get("preferredName") or d.get("fullName")
            last = d.get("lastName") or d.get("last_name") or d.get("familyName")
            aid = d.get("id") or d.get("athleteId") or d.get("athlete_id")
            is_healthy = None
            if "status" in d and isinstance(d.get("status"), dict):
                st = d.get("status")
                is_healthy = st.get("type") != "injured" if st else None

        return cls(
            first_name=first,
            last_name=last,
            position=(d.get("position") or (meta.get("position") if isinstance(meta.get("position"), str) else None) or d.get("pos")),
            id=str(aid) if aid is not None else None,
            is_healthy=(bool(is_healthy) if is_healthy is not None else None),
            slot=d.get("slot"),
            rank=d.get("rank"),
            meta=meta,
        )

    def to_dict(self) -> dict:
        # Convert to plain dict suitable for JSON serialization
        data = asdict(self)
        # Ensure meta is serializable (best-effort)
        try:
            import json as _json

            _json.dumps(data.get("meta", {}))
        except Exception:
            data["meta"] = {k: str(v) for k, v in (data.get("meta") or {}).items()}
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
