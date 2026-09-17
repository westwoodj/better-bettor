"""Ingest current NFL skill-position rosters from ESPN into the local DB."""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from nfl_data_aggregator.adapters.espn_api import NFLClient
from nfl_data_aggregator.db.engine import get_session_factory, init_db
from nfl_data_aggregator.ingestion.espn_ingestor import ESPNIngestor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", help="Ingest one ESPN team ID instead of all teams")
    parser.add_argument("--force", action="store_true", help="Bypass any local roster cache")
    args = parser.parse_args()

    init_db()
    session = get_session_factory()()
    try:
        client = NFLClient()
        team_ids = [args.team_id] if args.team_id else [
            str(team.get("team", {}).get("id"))
            for sport in (client._load_all_teams() or {}).get("sports", [])
            for league in sport.get("leagues", []) or []
            for team in league.get("teams", [])
            if team.get("team", {}).get("id")
        ]
        ingestor = ESPNIngestor(session, client)
        for team_id in dict.fromkeys(team_ids):
            print(ingestor.ingest_roster(team_id, force=args.force))
    finally:
        session.close()


if __name__ == "__main__":
    main()
