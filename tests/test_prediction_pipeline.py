"""Integration test for the prediction pipeline with mocked DSPy LM."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import json
from unittest.mock import patch, MagicMock
import pytest

try:
    import dspy
    HAS_DSPY = True
except ImportError:
    HAS_DSPY = False

from nfl_data_aggregator.pipeline.prediction_pipeline import PredictionPipeline, PredictionResult


def _mock_litellm_completion(**kwargs):
    """Mock litellm.completion to return structured DSPy-compatible responses."""
    messages = kwargs.get("messages", [])

    # Determine which stage we're in by looking at the prompt content
    prompt_text = ""
    for msg in messages:
        if isinstance(msg, dict):
            prompt_text += msg.get("content", "")

    predicted_stats_json = json.dumps({
        "pass_yards": {"floor": 230, "expected": 285, "ceiling": 340},
        "pass_tds": {"floor": 1, "expected": 2, "ceiling": 3},
        "rush_yards": {"floor": 10, "expected": 25, "ceiling": 45},
    })

    if "trend_analysis" in prompt_text and "predicted_stats" not in prompt_text:
        # Stage 2: Player analysis
        response_json = json.dumps({
            "reasoning": "Analyzing recent performance trends and matchup factors.",
            "trend_analysis": "Mahomes has been consistent with around 283 passing yards per game over the last 8 weeks.",
            "matchup_assessment": "Buffalo allows 225 pass yards per game, slightly below average.",
            "key_factors": "Strong arm, home field advantage, consistent production",
            "risk_factors": "Strong Buffalo pass rush, cold weather potential",
        })
    else:
        # Stage 3: Prediction generation
        response_json = json.dumps({
            "reasoning": "Based on season average of 283 yards and Buffalo allowing 225, expecting around 285.",
            "predicted_stats": predicted_stats_json,
        })

    # Build mock response matching litellm response structure
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = response_json
    mock_message.tool_calls = None
    mock_choice.message = mock_message
    mock_choice.finish_reason = "stop"
    mock_response.choices = [mock_choice]
    mock_response.model = "test-model"
    mock_response.id = "test-id"
    mock_response.created = 1234567890
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)

    return mock_response


@pytest.mark.skipif(not HAS_DSPY, reason="dspy not installed")
def test_pipeline_end_to_end(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile, sample_prop_lines):
    """Full pipeline with mocked litellm producing structured output."""

    # Configure DSPy with a model that will be intercepted
    lm = dspy.LM(model="openai/test-model", api_key="test-key", api_base="http://localhost:1")
    dspy.configure(lm=lm)

    with patch("litellm.completion", side_effect=_mock_litellm_completion):
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

    lm = dspy.LM(model="openai/test-model", api_key="test-key", api_base="http://localhost:1")
    dspy.configure(lm=lm)

    with patch("litellm.completion", side_effect=_mock_litellm_completion):
        pipeline = PredictionPipeline(session)
        result = pipeline.predict(sample_player.player_id, sample_game.game_id)

    # Should have prop comparisons
    assert len(result.prop_comparisons) > 0

    # pass_yards line 275.5, predicted 285 -> edge > 0 -> over
    pass_comp = [c for c in result.prop_comparisons if c["market"] == "pass_yards"]
    if pass_comp:
        assert pass_comp[0]["edge"] > 0
        assert pass_comp[0]["recommendation"] == "over"
