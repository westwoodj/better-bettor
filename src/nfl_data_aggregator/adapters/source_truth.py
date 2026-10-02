import json
from pathlib import Path
from typing import Any


def load_local_dataset(path: str) -> list[dict[str, Any]]:
    """Load a local JSON/NDJSON dataset as the 'source truth'.

    This is an example helper that you can extend to read CSVs, Parquet,
    databases, or S3 files. It intentionally keeps IO simple so it works on
    small local files for development.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source truth file not found: {path}")

    if p.suffix.lower() in (".json",):
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                # wrap single-object JSON
                return [data]
            return list(data)

    # For line-delimited JSON
    records = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # skip bad lines but continue
                continue
    return records


def find_team_in_source(
    records: list[dict[str, Any]], team_key: str
) -> dict[str, Any] | None:
    """Simple helper to match a team record by team key/name."""
    for r in records:
        if r.get("team_id") == team_key or r.get("team_name") == team_key:
            return r
    return None
