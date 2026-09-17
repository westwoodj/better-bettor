"""Tests for data quality confidence scorer."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.pipeline.confidence import DataQualityConfidence, DataQualityScore
from nfl_data_aggregator.pipeline.context_models import (
    PredictionContext, PlayerProfile, GameStats, SeasonAverages,
    MatchupContext, GameEnvironment, PropLineContext,
)


def _make_full_context():
    """Build a rich PredictionContext with all sections populated."""
    games = [
        GameStats(game_id=f"g{i}", week=i, season=2025, opponent="OPP",
                  pass_yards=250 + i * 10, source="nflverse")
        for i in range(1, 11)
    ]
    return PredictionContext(
        player=PlayerProfile(
            player_id="p1", name="Test QB", team="KC",
            position="QB", status="active", experience=7,
        ),
        recent_games=games,
        season_averages=SeasonAverages(games_played=10, avg_pass_yards=295.0),
        matchup=MatchupContext(game_id="g11", opponent="BUF", home_away="home"),
        environment=GameEnvironment(venue="Arrowhead Stadium"),
        prop_lines=[PropLineContext(market="pass_yards", line_value=275.5)],
        roster_verified=True,
    )


def _make_sparse_context():
    """Build a minimal context with little data."""
    return PredictionContext(
        player=PlayerProfile(
            player_id="p2", name="Backup QB", team="KC",
            position="QB", status="questionable",
        ),
        recent_games=[
            GameStats(game_id="g1", week=2, season=2025, opponent="OPP",
                      pass_yards=150, source="nflverse"),
        ],
        season_averages=SeasonAverages(games_played=1, avg_pass_yards=150.0),
    )


def test_full_context_high_score():
    scorer = DataQualityConfidence()
    ctx = _make_full_context()
    result = scorer.score(ctx)

    assert isinstance(result, DataQualityScore)
    assert result.total >= 70
    assert result.grade in ("A", "B")
    assert "games_played" in result.breakdown
    assert "source_agreement" in result.breakdown


def test_sparse_context_low_score():
    scorer = DataQualityConfidence()
    ctx = _make_sparse_context()
    result = scorer.score(ctx)

    assert result.total < 50
    assert result.grade in ("D", "F")


def test_games_played_penalty():
    scorer = DataQualityConfidence()

    # 0 games
    ctx = PredictionContext(
        player=PlayerProfile(player_id="p1", name="X", team="Y"),
        season_averages=SeasonAverages(games_played=0),
    )
    result = scorer.score(ctx)
    assert result.breakdown["games_played"]["score"] == 0.0

    # 8+ games -> 100
    ctx2 = _make_full_context()
    result2 = scorer.score(ctx2)
    assert result2.breakdown["games_played"]["score"] == 100.0


def test_injury_status_scoring():
    scorer = DataQualityConfidence()

    for status, expected_min in [("active", 100), ("probable", 85), ("questionable", 55), ("doubtful", 35)]:
        ctx = PredictionContext(
            player=PlayerProfile(player_id="p1", name="X", team="Y", status=status),
        )
        result = scorer.score(ctx)
        assert result.breakdown["injury_clarity"]["score"] >= expected_min


def test_multi_source_bonus():
    scorer = DataQualityConfidence()
    games = [
        GameStats(game_id="g1", week=1, season=2025, opponent="OPP", source="nflverse"),
        GameStats(game_id="g2", week=2, season=2025, opponent="OPP", source="espn"),
    ]
    ctx = PredictionContext(
        player=PlayerProfile(player_id="p1", name="X", team="Y"),
        recent_games=games,
        season_averages=SeasonAverages(games_played=2),
    )
    result = scorer.score(ctx)
    assert result.breakdown["source_agreement"]["score"] == 100.0


def test_single_source_default():
    scorer = DataQualityConfidence()
    games = [
        GameStats(game_id="g1", week=1, season=2025, opponent="OPP", source="nflverse"),
    ]
    ctx = PredictionContext(
        player=PlayerProfile(player_id="p1", name="X", team="Y"),
        recent_games=games,
        season_averages=SeasonAverages(games_played=1),
    )
    result = scorer.score(ctx)
    assert result.breakdown["source_agreement"]["score"] == 80.0


def test_roster_verified_scoring():
    scorer = DataQualityConfidence()

    # Verified roster -> 100
    ctx_verified = _make_full_context()
    ctx_verified.roster_verified = True
    result_verified = scorer.score(ctx_verified)
    assert result_verified.breakdown["roster_verified"]["score"] == 100.0

    # Unverified with warnings -> 20
    ctx_warn = _make_full_context()
    ctx_warn.roster_verified = False
    ctx_warn.roster_warnings = ["Player not found on roster"]
    result_warn = scorer.score(ctx_warn)
    assert result_warn.breakdown["roster_verified"]["score"] == 20.0

    # Not checked (no warnings, not verified) -> 50
    ctx_unk = _make_full_context()
    ctx_unk.roster_verified = False
    ctx_unk.roster_warnings = []
    result_unk = scorer.score(ctx_unk)
    assert result_unk.breakdown["roster_verified"]["score"] == 50.0

    # Verified should score significantly higher than unverified
    assert result_verified.total > result_warn.total


def test_score_components_sum_to_total():
    scorer = DataQualityConfidence()
    ctx = _make_full_context()
    result = scorer.score(ctx)

    # Weighted sum
    computed = sum(
        v["score"] * v["weight"] for v in result.breakdown.values()
    )
    assert abs(result.total - round(computed, 1)) < 0.1
