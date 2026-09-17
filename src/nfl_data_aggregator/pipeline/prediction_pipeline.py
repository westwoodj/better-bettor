"""Pipeline orchestrator wiring Stages 1-3 plus hallucination checking and confidence scoring."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from .context_assembler import ContextAssembler
from .context_models import PredictionContext
from .player_analysis import PlayerAnalysis
from .prediction_generator import PredictionGenerator
from .hallucination_checker import HallucinationChecker, HallucinationResult
from .confidence import DataQualityConfidence, DataQualityScore
from ..db.repository import PredictionRepo

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


@dataclass
class PredictionResult:
    """Complete result from the prediction pipeline."""
    player_id: str
    game_id: str
    predicted_stats: dict = field(default_factory=dict)
    confidence_score: float = 0.0
    confidence_breakdown: dict = field(default_factory=dict)
    reasoning: str = ""
    trend_analysis: str = ""
    matchup_assessment: str = ""
    key_factors: str = ""
    risk_factors: str = ""
    hallucination_check: Optional[HallucinationResult] = None
    data_snapshot_hash: str = ""
    prop_comparisons: list[dict] = field(default_factory=list)


class PredictionPipeline:
    """Orchestrates the multi-stage prediction pipeline."""

    def __init__(self, session: Session, espn_client=None):
        self.session = session
        self.assembler = ContextAssembler(session, espn_client=espn_client)
        self.analyzer = PlayerAnalysis()
        self.generator = PredictionGenerator()
        self.checker = HallucinationChecker()
        self.confidence = DataQualityConfidence()
        self.prediction_repo = PredictionRepo(session)

    def predict(self, player_id: str, game_id: str) -> PredictionResult:
        """Run the full prediction pipeline for a player and game.

        Stages:
        1. Context assembly (deterministic)
        2. Data quality confidence scoring (deterministic)
        3. Player analysis (DSPy, temp=0.3)
        4. Prediction generation (DSPy, temp=0.1)
        5. Hallucination check (deterministic) — retry Stage 4 up to 3 times on failure
        6. Prop line comparison (deterministic)
        7. Save to predictions table
        """
        # Stage 1: Context assembly
        logger.info("Stage 1: Assembling context for player=%s game=%s", player_id, game_id)
        context = self.assembler.assemble(player_id, game_id)

        if context.roster_warnings:
            for warning in context.roster_warnings:
                logger.warning("ROSTER WARNING: %s", warning)
        if context.roster_verified:
            logger.info("Roster verified for %s on %s", context.player.name, context.player.team)

        # Stage 2: Data quality confidence
        logger.info("Stage 2: Scoring data quality confidence")
        quality = self.confidence.score(context)

        # Stage 3: Player analysis (DSPy)
        logger.info("Stage 3: Running player analysis")
        analysis_result = self.analyzer(
            player_context=context.format_player_section() + "\n" + context.format_recent_games(),
            matchup_context=context.format_matchup_section(),
            game_environment=context.format_environment_section(),
        )

        trend_analysis = getattr(analysis_result, "trend_analysis", "")
        matchup_assessment = getattr(analysis_result, "matchup_assessment", "")
        key_factors = getattr(analysis_result, "key_factors", "")
        risk_factors = getattr(analysis_result, "risk_factors", "")

        analysis_text = (
            f"Trend Analysis: {trend_analysis}\n"
            f"Matchup Assessment: {matchup_assessment}\n"
            f"Key Factors: {key_factors}\n"
            f"Risk Factors: {risk_factors}"
        )

        # Stage 4 + 5: Prediction generation with hallucination check retry
        predicted_stats = {}
        reasoning = ""
        hallucination_result = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info("Stage 4: Prediction generation (attempt %d/%d)", attempt, MAX_RETRIES)
            pred_result = self.generator(
                player_analysis=analysis_text,
                player_context=context.format_player_section() + "\n" + context.format_recent_games(),
                historical_baselines=context.format_baselines(),
            )

            raw_stats = getattr(pred_result, "predicted_stats", "{}")
            predicted_stats = PredictionGenerator.parse_predicted_stats(raw_stats)
            reasoning = getattr(pred_result, "reasoning", "")

            # Stage 5: Hallucination check
            logger.info("Stage 5: Hallucination check (attempt %d/%d)", attempt, MAX_RETRIES)
            hallucination_result = self.checker.check_prediction(
                reasoning_text=reasoning + "\n" + analysis_text,
                predicted_stats=predicted_stats,
                context=context,
            )

            if hallucination_result.passed:
                logger.info("Hallucination check passed on attempt %d", attempt)
                break
            else:
                logger.warning(
                    "Hallucination check failed on attempt %d: %d violations",
                    attempt, len(hallucination_result.violations),
                )

        # Stage 6: Prop line comparison
        prop_comparisons = self._compare_props(predicted_stats, context)

        # Stage 7: Save prediction
        snapshot_hash = context.compute_snapshot_hash()
        self.prediction_repo.add(
            player_id=player_id,
            game_id=game_id,
            predicted_stats=predicted_stats,
            confidence_score=quality.total,
            confidence_breakdown=quality.breakdown,
            recommended_props=[p for p in prop_comparisons if p.get("edge", 0) > 0],
            reasoning_trace=reasoning + "\n---\n" + analysis_text,
            data_snapshot_hash=snapshot_hash,
            model_version="phase1-v0.2.0",
        )
        self.session.commit()

        return PredictionResult(
            player_id=player_id,
            game_id=game_id,
            predicted_stats=predicted_stats,
            confidence_score=quality.total,
            confidence_breakdown=quality.breakdown,
            reasoning=reasoning,
            trend_analysis=trend_analysis,
            matchup_assessment=matchup_assessment,
            key_factors=key_factors,
            risk_factors=risk_factors,
            hallucination_check=hallucination_result,
            data_snapshot_hash=snapshot_hash,
            prop_comparisons=prop_comparisons,
        )

    def _compare_props(self, predicted_stats: dict, context: PredictionContext) -> list[dict]:
        """Compare predicted stats against prop lines."""
        comparisons = []
        # Map market names to our stat keys
        market_to_stat = {
            "passing_yards": "pass_yards",
            "pass_yards": "pass_yards",
            "passing_tds": "pass_tds",
            "pass_tds": "pass_tds",
            "rushing_yards": "rush_yards",
            "rush_yards": "rush_yards",
            "receiving_yards": "receiving_yards",
            "receptions": "receptions",
            "rushing_tds": "rush_tds",
            "rush_tds": "rush_tds",
            "receiving_tds": "receiving_tds",
        }

        for prop in context.prop_lines:
            stat_key = market_to_stat.get(prop.market.lower(), prop.market.lower())
            pred = predicted_stats.get(stat_key)
            if pred is None or not isinstance(pred, dict):
                continue

            expected = pred.get("expected")
            if expected is None:
                continue

            edge = expected - prop.line_value
            recommendation = "over" if edge > 0 else "under"

            comparisons.append({
                "market": prop.market,
                "line": prop.line_value,
                "predicted": expected,
                "floor": pred.get("floor"),
                "ceiling": pred.get("ceiling"),
                "edge": round(edge, 1),
                "recommendation": recommendation,
                "sportsbook": prop.sportsbook,
            })

        return comparisons
