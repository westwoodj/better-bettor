"""Example runner for the NFL Data Aggregator scaffold.

This script uses the RecommendationService with mocked adapters and the
GoogleGenAIClient's fallback to demonstrate the flow without real API keys.
"""
import os
import sys
from datetime import datetime, timezone

# Ensure the `src` folder is on sys.path so this example can be run without
# installing the package into the environment. This is common for projects
# using the src/ layout.
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.models import Matchup
from nfl_data_aggregator.services.recommendation_service import RecommendationService


def pretty_print_model(m):
    """Print a model-like object safely across pydantic versions and fallbacks.

    Preference order:
    - model_dump_json (pydantic v2)
    - json() (legacy)
    - dict() -> json
    - __dict__ -> json
    - str()
    """
    import json

    if m is None:
        print("<no parsed output>")
        return

    # pydantic v2
    if hasattr(m, "model_dump_json"):
        try:
            print(m.model_dump_json(indent=2))
            return
        except Exception:
            pass

    # older pydantic or fallback
    if hasattr(m, "json"):
        try:
            # json() in pydantic v2 no longer accepts indent; guard it
            print(m.json(indent=2))
            return
        except TypeError:
            try:
                # try without indent
                print(m.json())
                return
            except Exception:
                pass

    # dict-like
    try:
        if hasattr(m, "dict"):
            print(json.dumps(m.dict(), indent=2, default=str, ensure_ascii=False))
            return
    except Exception:
        pass

    # fallback to __dict__ / str
    try:
        print(json.dumps(getattr(m, "__dict__", str(m)), indent=2, default=str, ensure_ascii=False))
    except Exception:
        print(str(m))


def main():
    matchup = Matchup(
        matchup_id="2025-10-12-NE-PHI",
        home_team="NE",
        away_team="PHI",
        start_time=datetime.now(timezone.utc).date(),
    )

    svc = RecommendationService()
    resp = svc.recommend_for_matchup(matchup)
    print("RAW MODEL RESPONSE:\n")
    print(resp.raw_text)
    print("\nPARSED RECOMMENDATION:\n")
    pretty_print_model(resp.parsed)


if __name__ == "__main__":
    main()
