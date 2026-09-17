"""Stage 2: DSPy player analysis module.

Uses ChainOfThought to analyze player trends, matchup factors,
and risk assessment based on the assembled context.
"""

import dspy


class PlayerAnalysisSignature(dspy.Signature):
    """Analyze an NFL player's recent performance trends, matchup factors,
    and key risk/opportunity factors for an upcoming game.

    You are a professional NFL analyst. Analyze ONLY the data provided below.
    Do NOT fabricate statistics or cite data not present in the context.
    """

    player_context: str = dspy.InputField(desc="Player profile, recent game stats, and season averages")
    matchup_context: str = dspy.InputField(desc="Opponent defense profile and matchup details")
    game_environment: str = dspy.InputField(desc="Venue, weather, and game type information")

    trend_analysis: str = dspy.OutputField(desc="Analysis of recent performance trends (2-3 sentences)")
    matchup_assessment: str = dspy.OutputField(desc="Assessment of how the matchup favors or challenges the player (2-3 sentences)")
    key_factors: str = dspy.OutputField(desc="Comma-separated list of 3-5 key positive factors for the player's performance")
    risk_factors: str = dspy.OutputField(desc="Comma-separated list of 2-4 risk or downside factors")


class PlayerAnalysis(dspy.Module):
    """DSPy module for Stage 2 player analysis."""

    def __init__(self):
        super().__init__()
        self.analyze = dspy.ChainOfThought(PlayerAnalysisSignature)

    def forward(self, player_context: str, matchup_context: str, game_environment: str):
        return self.analyze(
            player_context=player_context,
            matchup_context=matchup_context,
            game_environment=game_environment,
        )
