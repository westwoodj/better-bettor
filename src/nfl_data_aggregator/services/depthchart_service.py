from typing import Any, Dict, Optional
import logging
import re
from pathlib import Path

from ..adapters.espn_api import NFLClient
from ..models import Athlete

logger = logging.getLogger(__name__)


class DepthChartService:
    """Parse ESPN depth chart JSON payloads into per-schema pandas DataFrames.

    Produces a dict mapping sanitized names of the form '{team_id}_{schema_name}_{year}'
    to pandas.DataFrame objects. Athletes are represented by the `Athlete` dataclass.
    """

    def __init__(self, nfl_client: Optional[NFLClient] = None):
        self.nfl = nfl_client or NFLClient()

    def parse_from_file(self, file_path: str, team_id: Optional[str] = None, year: Optional[int] = None, force: bool = False) -> Dict[str, Any]:
        p = Path(file_path)
        with p.open("r", encoding="utf-8") as fh:
            import json

            data = json.load(fh)
        return self.parse_depthchart(data=data, team_id=team_id or self._infer_team_id_from_filename(p.stem), year=year or self._infer_year_from_filename(p.stem), force=force)

    def _infer_team_id_from_filename(self, stem: str) -> Optional[str]:
        # Example filename: '2-2025' -> team_id 2
        m = re.match(r"(\d+)-\d{4}", stem)
        return m.group(1) if m else None

    def _infer_year_from_filename(self, stem: str) -> Optional[int]:
        m = re.match(r"\d+-(\d{4})", stem)
        return int(m.group(1)) if m else None

    def _sanitize_schema_name(self, name: str) -> str:
        # replace spaces with underscores, remove non-alphanumeric/underscore
        s = name.strip().replace(" ", "_")
        s = re.sub(r"[^0-9A-Za-z_-]", "", s)
        return s

    def parse_depthchart(self, data: dict, team_id: Optional[str], year: Optional[int], force: bool = False) -> Dict[str, Any]:
        """Parse depth chart JSON response into DataFrames per schema.

        Returns a dict: { 'teamid_schema_year': DataFrame }
        """
        try:
            import pandas as pd
        except Exception as exc:
            raise RuntimeError("pandas is required for depth chart parsing; pip install pandas") from exc

        items = data.get("items", []) if isinstance(data, dict) else []
        result: Dict[str, Any] = {}

        for item in items:
            schema_name = item.get("name") or item.get("displayName") or "schema"
            sanitized = self._sanitize_schema_name(schema_name)
            rows = []
            positions = item.get("positions") or {}
            for pos_key, pos_val in positions.items():
                pos_info = pos_val.get("position") or {}
                pos_abbr = pos_info.get("abbreviation") or pos_info.get("displayName") or pos_info.get("name") or pos_key

                athletes = pos_val.get("athletes") or []
                for aentry in athletes:
                    slot = aentry.get("slot")
                    rank = aentry.get("rank")
                    athlete_obj = aentry.get("athlete")
                    athlete_data = None

                    # athlete_obj may be a dict containing a $ref or full data
                    if isinstance(athlete_obj, dict) and "$ref" in athlete_obj:
                        ref = athlete_obj.get("$ref")
                        # attempt to fetch resolved athlete resource
                        resolved = self.nfl.fetch_by_ref(ref, force=force)
                        # resolved might return {'id': '1234'} or full athlete
                        athlete_data = resolved if isinstance(resolved, dict) else None
                    elif isinstance(athlete_obj, dict) and athlete_obj.get("id"):
                        athlete_data = athlete_obj
                    else:
                        # unknown shape: store raw
                        athlete_data = {"ref": athlete_obj}

                    # Merge in the slot/rank for Athlete.from_dict
                    merged = {"slot": slot, "rank": rank}
                    if athlete_data:
                        # if resolved contains key 'person' or 'athlete', try to unwrap
                        if "person" in athlete_data and isinstance(athlete_data["person"], dict):
                            merged["athlete"] = athlete_data["person"]
                        elif "athlete" in athlete_data and isinstance(athlete_data["athlete"], dict):
                            merged["athlete"] = athlete_data["athlete"]
                        else:
                            # assume the resolved dict itself contains name/id
                            merged.update(athlete_data)

                    # also attach position for context
                    merged["position"] = pos_abbr

                    athlete = Athlete.from_dict(merged)
                    rows.append(athlete.to_dict())

            # Build DataFrame grouped by position and slot, ordered by rank
            if rows:
                df = pd.DataFrame(rows)
                # ensure numeric types for ordering
                for c in ("slot", "rank"):
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                df.sort_values(by=["position", "slot", "rank"], inplace=True, na_position="last")
                # reset index
                df.reset_index(drop=True, inplace=True)
            else:
                df = pd.DataFrame()

            key = f"{team_id}_{sanitized}_{year}" if team_id and year else f"{sanitized}_{year or 'unknown'}"
            result[key] = df

        return result

