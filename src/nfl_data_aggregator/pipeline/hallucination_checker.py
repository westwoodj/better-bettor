"""Deterministic hallucination checker for prediction pipeline output.

Pure Python — no LLM calls. Uses regex to extract numeric claims from
reasoning text and verifies them against source data.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .context_models import PredictionContext


@dataclass
class NumericClaim:
    """A numeric claim extracted from reasoning text."""
    stat_type: str      # e.g., "pass_yards", "rush_tds"
    value: float
    claim_text: str     # The original matched text
    claim_type: str     # "average", "specific_week", "total", "general"
    week: int | None = None


@dataclass
class Violation:
    """A detected hallucination or implausibility."""
    claim: NumericClaim
    reason: str
    severity: str = "warning"  # "warning" or "error"


@dataclass
class HallucinationResult:
    """Result of a hallucination check."""
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    prediction_sanity: dict = field(default_factory=dict)


# Plausible single-game ranges for NFL stat categories
PLAUSIBLE_RANGES = {
    "pass_yards": (0, 600),
    "pass_tds": (0, 8),
    "pass_completions": (0, 50),
    "pass_attempts": (0, 70),
    "interceptions": (0, 6),
    "rush_yards": (-10, 300),
    "rush_tds": (0, 5),
    "rush_attempts": (0, 40),
    "receptions": (0, 20),
    "receiving_yards": (0, 350),
    "receiving_tds": (0, 5),
    "targets": (0, 25),
    "fantasy_points": (0, 80),
    "passer_rating": (0, 158.4),
}

# Regex patterns for extracting numeric claims from text
_CLAIM_PATTERNS = [
    # "averaging 265.3 passing yards"
    (r"averag\w*\s+(\d+\.?\d*)\s+(passing|pass)\s+yards?", "pass_yards", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+(rushing|rush)\s+yards?", "rush_yards", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+(receiving)\s+yards?", "receiving_yards", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+(receptions?)", "receptions", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+(passing|pass)\s+t(?:ouch)?d", "pass_tds", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+(rushing|rush)\s+t(?:ouch)?d", "rush_tds", "average"),
    (r"averag\w*\s+(\d+\.?\d*)\s+fantasy\s+points?", "fantasy_points", "average"),

    # "265 passing yards per game"
    (r"(\d+\.?\d*)\s+(passing|pass)\s+yards?\s+per\s+game", "pass_yards", "average"),
    (r"(\d+\.?\d*)\s+(rushing|rush)\s+yards?\s+per\s+game", "rush_yards", "average"),
    (r"(\d+\.?\d*)\s+(receiving)\s+yards?\s+per\s+game", "receiving_yards", "average"),

    # "threw for 300 yards" / "rushed for 150 yards"
    (r"threw\s+for\s+(\d+)\s+yards?", "pass_yards", "general"),
    (r"rushed\s+for\s+(\d+)\s+yards?", "rush_yards", "general"),
    (r"caught\s+(\d+)\s+pass", "receptions", "general"),
    (r"(\d+)\s+passing\s+yards?", "pass_yards", "general"),
    (r"(\d+)\s+rushing\s+yards?", "rush_yards", "general"),
    (r"(\d+)\s+receiving\s+yards?", "receiving_yards", "general"),
    (r"(\d+)\s+passing\s+t(?:ouch)?d", "pass_tds", "general"),
    (r"(\d+)\s+rushing\s+t(?:ouch)?d", "rush_tds", "general"),
    (r"(\d+)\s+receiving\s+t(?:ouch)?d", "receiving_tds", "general"),
    (r"(\d+)\s+receptions?", "receptions", "general"),
    (r"(\d+)\s+targets?", "targets", "general"),

    # "in week 5, had 280 yards"
    (r"week\s+(\d+).*?(\d+)\s+(passing|pass)\s+yards?", "pass_yards", "specific_week"),
    (r"week\s+(\d+).*?(\d+)\s+(rushing|rush)\s+yards?", "rush_yards", "specific_week"),
    (r"week\s+(\d+).*?(\d+)\s+(receiving)\s+yards?", "receiving_yards", "specific_week"),
]


class HallucinationChecker:
    """Deterministic checker for fabricated statistics in LLM output."""

    def extract_numeric_claims(self, text: str) -> list[NumericClaim]:
        """Extract numeric statistical claims from reasoning text."""
        claims = []
        text_lower = text.lower()

        for pattern, stat_type, claim_type in _CLAIM_PATTERNS:
            for match in re.finditer(pattern, text_lower):
                groups = match.groups()
                if claim_type == "specific_week":
                    week = int(groups[0])
                    value = float(groups[1])
                    claims.append(NumericClaim(
                        stat_type=stat_type,
                        value=value,
                        claim_text=match.group(0),
                        claim_type="specific_week",
                        week=week,
                    ))
                else:
                    value = float(groups[0])
                    claims.append(NumericClaim(
                        stat_type=stat_type,
                        value=value,
                        claim_text=match.group(0),
                        claim_type=claim_type,
                    ))

        return claims

    def verify_claims(self, claims: list[NumericClaim], context: PredictionContext) -> list[Violation]:
        """Verify extracted claims against source data."""
        violations = []

        for claim in claims:
            # Check plausible ranges
            if claim.stat_type in PLAUSIBLE_RANGES:
                lo, hi = PLAUSIBLE_RANGES[claim.stat_type]
                if claim.value < lo or claim.value > hi:
                    violations.append(Violation(
                        claim=claim,
                        reason=f"Value {claim.value} outside plausible range [{lo}, {hi}] for {claim.stat_type}",
                        severity="error",
                    ))

            # Verify claimed averages against actual
            if claim.claim_type == "average" and context.season_averages.games_played > 0:
                actual_avg = self._get_actual_average(claim.stat_type, context)
                if actual_avg is not None:
                    tolerance = max(actual_avg * 0.10, 5.0)  # 10% or at least 5
                    if abs(claim.value - actual_avg) > tolerance:
                        violations.append(Violation(
                            claim=claim,
                            reason=f"Claimed average {claim.value} for {claim.stat_type} differs from actual {actual_avg:.1f} (tolerance: {tolerance:.1f})",
                            severity="error",
                        ))

            # Verify specific week references
            if claim.claim_type == "specific_week" and claim.week is not None:
                actual_value = self._get_week_stat(claim.stat_type, claim.week, context)
                if actual_value is not None:
                    tolerance = max(abs(actual_value) * 0.05, 1.0)  # 5% or 1
                    if abs(claim.value - actual_value) > tolerance:
                        violations.append(Violation(
                            claim=claim,
                            reason=f"Claimed {claim.stat_type}={claim.value} in week {claim.week} but actual was {actual_value}",
                            severity="error",
                        ))

        return violations

    def check_prediction(
        self,
        reasoning_text: str,
        predicted_stats: dict,
        context: PredictionContext,
    ) -> HallucinationResult:
        """Full hallucination check on reasoning text and predicted stats.

        Returns a HallucinationResult with pass/fail status and details.
        """
        # Check reasoning text claims
        claims = self.extract_numeric_claims(reasoning_text)
        violations = self.verify_claims(claims, context)

        # Prediction sanity checks
        sanity = {}
        for stat_name, stat_pred in predicted_stats.items():
            if not isinstance(stat_pred, dict):
                continue
            floor = stat_pred.get("floor")
            expected = stat_pred.get("expected")
            ceiling = stat_pred.get("ceiling")

            stat_sanity = {"valid": True, "issues": []}

            # Floor <= expected <= ceiling
            if floor is not None and expected is not None and ceiling is not None:
                if not (floor <= expected <= ceiling):
                    stat_sanity["valid"] = False
                    stat_sanity["issues"].append(
                        f"floor ({floor}) <= expected ({expected}) <= ceiling ({ceiling}) violated"
                    )

            # Expected value within plausible bounds
            if expected is not None and stat_name in PLAUSIBLE_RANGES:
                lo, hi = PLAUSIBLE_RANGES[stat_name]
                if expected < lo or expected > hi:
                    stat_sanity["valid"] = False
                    stat_sanity["issues"].append(
                        f"expected value {expected} outside plausible range [{lo}, {hi}]"
                    )

            # Floor within plausible bounds
            if floor is not None and stat_name in PLAUSIBLE_RANGES:
                lo, hi = PLAUSIBLE_RANGES[stat_name]
                if floor < lo:
                    stat_sanity["valid"] = False
                    stat_sanity["issues"].append(f"floor {floor} below minimum {lo}")

            # Ceiling within plausible bounds
            if ceiling is not None and stat_name in PLAUSIBLE_RANGES:
                lo, hi = PLAUSIBLE_RANGES[stat_name]
                if ceiling > hi:
                    stat_sanity["valid"] = False
                    stat_sanity["issues"].append(f"ceiling {ceiling} above maximum {hi}")

            sanity[stat_name] = stat_sanity

        # Overall pass/fail
        has_errors = any(v.severity == "error" for v in violations)
        has_sanity_failures = any(not s["valid"] for s in sanity.values())
        passed = not has_errors and not has_sanity_failures

        return HallucinationResult(
            passed=passed,
            violations=violations,
            prediction_sanity=sanity,
        )

    def _get_actual_average(self, stat_type: str, context: PredictionContext) -> Optional[float]:
        """Get actual season average for a stat type from context."""
        avg_map = {
            "pass_yards": context.season_averages.avg_pass_yards,
            "pass_tds": context.season_averages.avg_pass_tds,
            "rush_yards": context.season_averages.avg_rush_yards,
            "rush_tds": context.season_averages.avg_rush_tds,
            "receptions": context.season_averages.avg_receptions,
            "receiving_yards": context.season_averages.avg_receiving_yards,
            "receiving_tds": context.season_averages.avg_receiving_tds,
            "fantasy_points": context.season_averages.avg_fantasy_points,
        }
        return avg_map.get(stat_type)

    def _get_week_stat(self, stat_type: str, week: int, context: PredictionContext) -> Optional[float]:
        """Get actual stat for a specific week from context."""
        for game in context.recent_games:
            if game.week == week:
                val = getattr(game, stat_type, None)
                return float(val) if val is not None else None
        return None
