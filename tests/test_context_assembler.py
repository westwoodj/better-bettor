"""Tests for context assembler (pipeline Stage 1)."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import pytest

from nfl_data_aggregator.pipeline.context_assembler import ContextAssembler
from nfl_data_aggregator.pipeline.context_models import PredictionContext


def test_assemble_basic(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile, sample_prop_lines):
    """Test full context assembly with all fixture data."""
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    assert isinstance(ctx, PredictionContext)
    assert ctx.player.name == "Patrick Mahomes"
    assert ctx.player.team == "KC"
    assert ctx.player.position == "QB"


def test_assemble_recent_games(session, sample_player, sample_game, sample_games_8_weeks):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    assert len(ctx.recent_games) == 8
    # Games should be sorted by week
    weeks = [g.week for g in ctx.recent_games]
    assert weeks == sorted(weeks)


def test_assemble_season_averages(session, sample_player, sample_game, sample_games_8_weeks):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    avgs = ctx.season_averages
    assert avgs.games_played == 8
    assert avgs.avg_pass_yards > 0
    assert avgs.avg_pass_tds > 0


def test_assemble_matchup(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    assert ctx.matchup is not None
    assert ctx.matchup.opponent == "BUF"
    assert ctx.matchup.home_away == "home"
    assert ctx.matchup.opponent_pass_yards_allowed == 225.5


def test_assemble_prop_lines(session, sample_player, sample_game, sample_games_8_weeks, sample_prop_lines):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    assert len(ctx.prop_lines) == 3
    markets = {p.market for p in ctx.prop_lines}
    assert "pass_yards" in markets


def test_assemble_player_not_found(session, sample_game):
    assembler = ContextAssembler(session)
    with pytest.raises(ValueError, match="Player not found"):
        assembler.assemble("nonexistent", sample_game.game_id)


def test_assemble_game_not_found(session, sample_player):
    assembler = ContextAssembler(session)
    with pytest.raises(ValueError, match="Game not found"):
        assembler.assemble(sample_player.player_id, "nonexistent")


def test_format_methods(session, sample_player, sample_game, sample_games_8_weeks, sample_defense_profile, sample_prop_lines):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    # Smoke test all format methods
    assert "Patrick Mahomes" in ctx.format_player_section()
    assert "Week" in ctx.format_recent_games()
    assert "BUF" in ctx.format_matchup_section()
    assert "Arrowhead" in ctx.format_environment_section()
    assert "games" in ctx.format_baselines().lower()
    assert "pass_yards" in ctx.format_prop_lines()


def test_roster_warnings_no_client(session, sample_player, sample_game, sample_games_8_weeks):
    """Without ESPN client, roster is not verified but no hard failure."""
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    assert ctx.roster_verified is False
    assert len(ctx.roster_warnings) > 0
    assert "no espn client" in ctx.roster_warnings[0].lower()


def test_snapshot_hash(session, sample_player, sample_game, sample_games_8_weeks):
    assembler = ContextAssembler(session)
    ctx = assembler.assemble(sample_player.player_id, sample_game.game_id)

    h = ctx.compute_snapshot_hash()
    assert isinstance(h, str)
    assert len(h) == 16

    # Same context should produce same hash
    h2 = ctx.compute_snapshot_hash()
    assert h == h2
