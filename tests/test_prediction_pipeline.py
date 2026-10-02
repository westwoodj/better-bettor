"""Integration test for the prediction pipeline with mocked DSPy LM."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import json

import pytest

try:
    import dspy
    HAS_DSPY = True
except ImportError:
    HAS_DSPY = False

from nfl_data_aggregator.pipeline.prediction_pipeline import (
    PredictionPipeline,
    PredictionResult,
)


def _dummy_lm():
    """DummyLM answering the two pipeline stages (player analysis, then prediction)."""
    predicted_stats_json = json.dumps({
        "pass_yards": {"floor": 230, "expected": 285, "ceiling": 340},
        "pass_tds": {"floor": 1, "expected": 2, "ceiling": 3},
        "rush_yards": {"floor": 10, "expected": 25, "ceiling": 45},
    })
    return dspy.utils.DummyLM([
        {
            "reasoning": "Analyzing recent performance trends and matchup factors.",
            "trend_analysis": "Mahomes has been consistent with around 283 passing yards per game over the last 8 weeks.",
            "matchup_assessment": "Buffalo ranks below average against the pass.",
            "key_factors": "Strong arm, home field advantage, consistent production",
            "risk_factors": "Strong Buffalo pass rush, cold weather potential",
        },
        {
            "reasoning": "Based on season average of 283 yards and a soft Buffalo pass defense, expecting around 285.",
            "predicted_stats": predicted_stats_json,
        },
    ])


@pytest.mark.skipif(not HAS_DSPY, reason="dspy not installed")
def test_pipeline_end_to_end(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile, sample_prop_lines):
    """Full pipeline with a DummyLM producing structured output."""

    dspy.configure(lm=_dummy_lm())

    pipeline = PredictionPipeline(session)
    result = pipeline.predict(sample_player.player_id, sample_game.game_id)

    assert isinstance(result, PredictionResult)
    assert result.player_id == sample_player.player_id
    assert result.game_id == sample_game.game_id
    assert result.confidence_score > 0
    assert result.data_snapshot_hash != ""


@pytest.mark.skipif(not HAS_DSPY, reason="dspy not installed")
def test_pipeline_prop_comparison(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile, sample_prop_lines):
    """Verify prop comparisons are generated."""

    dspy.configure(lm=_dummy_lm())

    pipeline = PredictionPipeline(session)
    result = pipeline.predict(sample_player.player_id, sample_game.game_id)

    # Should have prop comparisons
    assert len(result.prop_comparisons) > 0

    # pass_yards line 275.5, predicted 285 -> edge > 0 -> over
    pass_comp = [c for c in result.prop_comparisons if c["market"] == "pass_yards"]
    if pass_comp:
        assert pass_comp[0]["edge"] > 0
        assert pass_comp[0]["recommendation"] == "over"
