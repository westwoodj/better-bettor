"""Tests for the deterministic hallucination checker."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.pipeline.hallucination_checker import HallucinationChecker, PLAUSIBLE_RANGES
from nfl_data_aggregator.pipeline.context_models import (
    PredictionContext, PlayerProfile, GameStats, SeasonAverages,
)


def _make_context():
    """Build a minimal PredictionContext for testing."""
    return PredictionContext(
        player=PlayerProfile(player_id="p1", name="Test QB", team="KC", position="QB"),
        recent_games=[
            GameStats(game_id="g1", week=1, season=2025, opponent="DET",
                      pass_yards=280, pass_tds=3, rush_yards=25),
            GameStats(game_id="g2", week=2, season=2025, opponent="CIN",
                      pass_yards=310, pass_tds=2, rush_yards=30),
            GameStats(game_id="g3", week=3, season=2025, opponent="ATL",
                      pass_yards=260, pass_tds=1, rush_yards=18),
        ],
        season_averages=SeasonAverages(
            games_played=3,
            avg_pass_yards=283.3,
            avg_pass_tds=2.0,
            avg_rush_yards=24.3,
        ),
    )


def test_extract_numeric_claims_passing():
    checker = HallucinationChecker()
    text = "Mahomes is averaging 283 passing yards per game and has 2 passing TDs per game."
    claims = checker.extract_numeric_claims(text)

    assert len(claims) >= 2
    stat_types = {c.stat_type for c in claims}
    assert "pass_yards" in stat_types
    assert "pass_tds" in stat_types


def test_extract_numeric_claims_rushing():
    checker = HallucinationChecker()
    text = "He rushed for 45 rushing yards last week."
    claims = checker.extract_numeric_claims(text)

    assert any(c.stat_type == "rush_yards" for c in claims)


def test_extract_numeric_claims_week_specific():
    checker = HallucinationChecker()
    text = "In week 2, he had 310 passing yards."
    claims = checker.extract_numeric_claims(text)

    week_claims = [c for c in claims if c.claim_type == "specific_week"]
    assert len(week_claims) >= 1
    assert week_claims[0].week == 2
    assert week_claims[0].value == 310.0


def test_verify_claims_fabricated_average():
    """Fabricated average should be detected."""
    checker = HallucinationChecker()
    context = _make_context()

    # Claim: averaging 350 passing yards (actual is ~283)
    text = "He is averaging 350 passing yards per game."
    claims = checker.extract_numeric_claims(text)
    violations = checker.verify_claims(claims, context)

    assert len(violations) > 0
    assert any("average" in v.reason.lower() or "differs" in v.reason.lower() for v in violations)


def test_verify_claims_correct_average():
    """Correct average should pass."""
    checker = HallucinationChecker()
    context = _make_context()

    text = "He is averaging 283 passing yards per game."
    claims = checker.extract_numeric_claims(text)
    violations = checker.verify_claims(claims, context)

    # Should have no errors (within 10% tolerance)
    errors = [v for v in violations if v.severity == "error"]
    assert len(errors) == 0


def test_verify_claims_plausible_range_violation():
    """Value outside plausible range should be caught."""
    checker = HallucinationChecker()
    context = _make_context()

    text = "He threw for 700 passing yards."
    claims = checker.extract_numeric_claims(text)
    violations = checker.verify_claims(claims, context)

    assert any("plausible range" in v.reason.lower() for v in violations)


def test_verify_specific_week_stat():
    """Incorrect week-specific claim should be caught."""
    checker = HallucinationChecker()
    context = _make_context()

    text = "In week 1, he had 350 passing yards."  # Actual was 280
    claims = checker.extract_numeric_claims(text)
    violations = checker.verify_claims(claims, context)

    assert len(violations) > 0


def test_check_prediction_clean():
    """Clean prediction passes hallucination check."""
    checker = HallucinationChecker()
    context = _make_context()

    predicted_stats = {
        "pass_yards": {"floor": 220, "expected": 280, "ceiling": 340},
        "pass_tds": {"floor": 1, "expected": 2, "ceiling": 3},
    }
    reasoning = "Based on season averages of 283 passing yards, expecting around 280."

    result = checker.check_prediction(reasoning, predicted_stats, context)
    assert result.passed is True
    assert len(result.violations) == 0


def test_check_prediction_floor_exceeds_ceiling():
    """Floor > ceiling should fail sanity check."""
    checker = HallucinationChecker()
    context = _make_context()

    predicted_stats = {
        "pass_yards": {"floor": 350, "expected": 280, "ceiling": 250},
    }
    reasoning = "Simple prediction."

    result = checker.check_prediction(reasoning, predicted_stats, context)
    assert result.passed is False
    assert "pass_yards" in result.prediction_sanity
    assert not result.prediction_sanity["pass_yards"]["valid"]


def test_check_prediction_exceeds_plausible():
    """Prediction exceeding plausible range should fail."""
    checker = HallucinationChecker()
    context = _make_context()

    predicted_stats = {
        "pass_yards": {"floor": 200, "expected": 700, "ceiling": 800},
    }
    reasoning = "He will have a record day."

    result = checker.check_prediction(reasoning, predicted_stats, context)
    assert result.passed is False
