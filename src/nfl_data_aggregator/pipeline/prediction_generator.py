"""Stage 3: DSPy prediction generation module.

Uses ChainOfThought to generate specific stat predictions with ranges,
grounded in the analysis from Stage 2 and the player's historical baselines.
"""

import json
import logging
import re

import dspy

logger = logging.getLogger(__name__)


class PredictionSignature(dspy.Signature):
    """Generate specific statistical predictions for an NFL player's upcoming game.

    Based on the analysis and historical data provided, predict the player's
    stat line with floor, expected, and ceiling values.

    IMPORTANT: All predictions must be grounded in the provided data.
    Do NOT invent statistics. Return predicted_stats as valid JSON.
    """

    player_analysis: str = dspy.InputField(desc="Trend analysis, matchup assessment, key factors, and risk factors from Stage 2")
    player_context: str = dspy.InputField(desc="Player profile and recent game stats")
    historical_baselines: str = dspy.InputField(desc="Season averages and historical performance baselines")

    predicted_stats: str = dspy.OutputField(
        desc='JSON object with stat predictions. Each stat has "floor", "expected", "ceiling" keys. '
             'Example: {"pass_yards": {"floor": 200, "expected": 265, "ceiling": 330}, '
             '"pass_tds": {"floor": 1, "expected": 2, "ceiling": 3}}'
    )
    reasoning: str = dspy.OutputField(desc="Brief explanation of the key drivers behind the predictions (2-3 sentences)")


class PredictionGenerator(dspy.Module):
    """DSPy module for Stage 3 prediction generation."""

    def __init__(self):
        super().__init__()
        self.predict = dspy.ChainOfThought(PredictionSignature)

    def forward(self, player_analysis: str, player_context: str, historical_baselines: str):
        return self.predict(
            player_analysis=player_analysis,
            player_context=player_context,
            historical_baselines=historical_baselines,
        )

    @staticmethod
    def parse_predicted_stats(raw: str) -> dict:
        """Parse the predicted_stats output, handling markdown fences and trailing commas."""
        text = raw.strip()

        # Remove markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Remove trailing commas before closing braces/brackets
        text = re.sub(r",\s*([}\]])", r"\1", text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse predicted_stats JSON: %s", text[:200])
            return {}
