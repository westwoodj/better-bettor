"""Tests for nflverse adapter with mocked nfl_data_py."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from unittest.mock import patch, MagicMock
import pytest

from nfl_data_aggregator.adapters.nflverse_adapter import NflverseAdapter


def _make_mock_weekly_df():
    """Create a mock DataFrame mimicking nfl_data_py.import_weekly_data output."""
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not installed")

    return pd.DataFrame([
        {
            "player_id": "00-0033873",
            "player_name": "P.Mahomes",
            "player_display_name": "Patrick Mahomes",
            "recent_team": "KC",
            "position": "QB",
            "week": 1,
            "season": 2025,
            "completions": 25,
            "attempts": 35,
            "passing_yards": 290,
            "passing_tds": 3,
            "interceptions": 1,
            "carries": 4,
            "rushing_yards": 22,
            "rushing_tds": 0,
            "receptions": 0,
            "targets": 0,
            "receiving_yards": 0,
            "receiving_tds": 0,
            "fantasy_points_ppr": 22.6,
        }
    ])


def _make_mock_roster_df():
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not installed")

    return pd.DataFrame([
        {
            "player_id": "00-0033873",
            "player_name": "Patrick Mahomes",
            "team": "KC",
            "position": "QB",
            "status": "Active",
            "height": "6-2",
            "weight": 225,
            "years_exp": 7,
        },
        {
            "player_id": "00-0099999",
            "player_name": "Some Linebacker",
            "team": "KC",
            "position": "LB",
            "status": "Active",
            "height": "6-3",
            "weight": 245,
            "years_exp": 3,
        },
    ])


def _make_mock_schedule_df():
    try:
        import pandas as pd
    except ImportError:
        pytest.skip("pandas not installed")

    return pd.DataFrame([
        {
            "game_id": "2025_01_KC_DET",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "DET",
            "gameday": "2025-09-07",
            "stadium": "Arrowhead Stadium",
            "home_score": 31,
            "away_score": 27,
            "temp": 72,
            "wind": 8,
        }
    ])


def test_import_weekly_data_normalizes():
    adapter = NflverseAdapter()
    mock_df = _make_mock_weekly_df()

    import nfl_data_aggregator.adapters.nflverse_adapter as mod
    original = mod._nfl_data_py

    mock_nfl = MagicMock()
    mock_nfl.import_weekly_data.return_value = mock_df
    mod._nfl_data_py = mock_nfl
    mod._import_attempted = True

    try:
        records = adapter.import_weekly_data([2025])
        assert len(records) == 1
        r = records[0]
        assert r["source"] == "nflverse"
        assert r["nflverse_id"] == "00-0033873"
        assert r["name"] == "Patrick Mahomes"
        assert r["pass_yards"] == 290
        assert r["pass_tds"] == 3
        assert r["rush_yards"] == 22
    finally:
        mod._nfl_data_py = original


def test_import_rosters_filters_skill_positions():
    adapter = NflverseAdapter()
    mock_df = _make_mock_roster_df()

    import nfl_data_aggregator.adapters.nflverse_adapter as mod
    original = mod._nfl_data_py

    mock_nfl = MagicMock()
    mock_nfl.import_rosters.return_value = mock_df
    mod._nfl_data_py = mock_nfl
    mod._import_attempted = True

    try:
        records = adapter.import_rosters([2025])
        assert len(records) == 1  # LB filtered out
        assert records[0]["name"] == "Patrick Mahomes"
        assert records[0]["weight"] == 225
    finally:
        mod._nfl_data_py = original


def test_import_schedule_normalizes():
    adapter = NflverseAdapter()
    mock_df = _make_mock_schedule_df()

    import nfl_data_aggregator.adapters.nflverse_adapter as mod
    original = mod._nfl_data_py

    mock_nfl = MagicMock()
    mock_nfl.import_schedules.return_value = mock_df
    mod._nfl_data_py = mock_nfl
    mod._import_attempted = True

    try:
        records = adapter.import_schedule([2025])
        assert len(records) == 1
        r = records[0]
        assert r["game_id"] == "2025_01_KC_DET"
        assert r["home_team"] == "KC"
        assert r["final_score"] == "31-27"
        assert r["weather_conditions"]["temp"] == 72
    finally:
        mod._nfl_data_py = original


def test_graceful_degradation_without_nfl_data_py():
    """Adapter returns empty results when nfl_data_py not available."""
    import nfl_data_aggregator.adapters.nflverse_adapter as mod

    original_mod = mod._nfl_data_py
    original_attempted = mod._import_attempted

    mod._nfl_data_py = None
    mod._import_attempted = True

    try:
        adapter = NflverseAdapter()
        assert adapter.import_weekly_data([2025]) == []
        assert adapter.import_rosters([2025]) == []
        assert adapter.import_schedule([2025]) == []
    finally:
        mod._nfl_data_py = original_mod
        mod._import_attempted = original_attempted
