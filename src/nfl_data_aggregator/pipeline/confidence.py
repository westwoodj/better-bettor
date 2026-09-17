"""Deterministic data quality confidence scorer (0-100).

Scores how much we can trust a prediction based on data availability and quality,
NOT model confidence. This is Phase 1 — stability and calibration scoring
will be added in Phase 2.
"""

from dataclasses import dataclass, field

from .context_models import PredictionContext


@dataclass
class DataQualityScore:
    """Confidence score with component breakdown."""
    total: float = 0.0
    breakdown: dict = field(default_factory=dict)

    @property
    def grade(self) -> str:
        if self.total >= 80:
            return "A"
        elif self.total >= 65:
            return "B"
        elif self.total >= 50:
            return "C"
        elif self.total >= 35:
            return "D"
        return "F"


class DataQualityConfidence:
    """Scores data quality for a PredictionContext on a 0-100 scale."""

    # Component weights (must sum to 1.0)
    WEIGHT_GAMES_PLAYED = 0.20
    WEIGHT_SOURCE_AGREEMENT = 0.15
    WEIGHT_INJURY_CLARITY = 0.15
    WEIGHT_DATA_COMPLETENESS = 0.15
    WEIGHT_DATA_FRESHNESS = 0.10
    WEIGHT_ROSTER_VERIFIED = 0.25

    def score(self, context: PredictionContext) -> DataQualityScore:
        """Compute data quality score for a prediction context."""
        breakdown = {}

        # 1. Games played (25%) — 100 if >=8 games, penalty below 4
        games = context.season_averages.games_played
        if games >= 8:
            games_score = 100.0
        elif games >= 4:
            games_score = 50.0 + (games - 4) * (50.0 / 4)
        elif games >= 1:
            games_score = games * (50.0 / 4)
        else:
            games_score = 0.0
        breakdown["games_played"] = {
            "score": games_score,
            "weight": self.WEIGHT_GAMES_PLAYED,
            "detail": f"{games} games played",
        }

        # 2. Source agreement (20%) — 80 default for single source, higher for cross-source
        sources = set()
        for g in context.recent_games:
            if g.source:
                sources.add(g.source)
        if len(sources) >= 2:
            source_score = 100.0
        elif len(sources) == 1:
            source_score = 80.0
        else:
            source_score = 40.0
        breakdown["source_agreement"] = {
            "score": source_score,
            "weight": self.WEIGHT_SOURCE_AGREEMENT,
            "detail": f"{len(sources)} data source(s)",
        }

        # 3. Injury clarity (20%)
        status = (context.player.status or "active").lower()
        injury_map = {
            "active": 100.0,
            "probable": 90.0,
            "questionable": 60.0,
            "doubtful": 40.0,
            "out": 20.0,
            "injured-reserve": 10.0,
            "ir": 10.0,
        }
        injury_score = injury_map.get(status, 70.0)
        breakdown["injury_clarity"] = {
            "score": injury_score,
            "weight": self.WEIGHT_INJURY_CLARITY,
            "detail": f"Status: {context.player.status or 'active'}",
        }

        # 4. Data completeness (20%) — % of context sections populated
        sections_present = 0
        total_sections = 5

        if context.recent_games:
            sections_present += 1
        if context.season_averages.games_played > 0:
            sections_present += 1
        if context.matchup is not None:
            sections_present += 1
        if context.environment.venue:
            sections_present += 1
        if context.prop_lines:
            sections_present += 1

        completeness_score = (sections_present / total_sections) * 100
        breakdown["data_completeness"] = {
            "score": completeness_score,
            "weight": self.WEIGHT_DATA_COMPLETENESS,
            "detail": f"{sections_present}/{total_sections} sections populated",
        }

        # 5. Data freshness (10%) — how recent is the game data
        freshness_score = 0.0
        if context.recent_games:
            max_week = max(g.week for g in context.recent_games)
            # Assume current week context; more recent data = higher score
            if max_week >= 15:
                freshness_score = 100.0
            elif max_week >= 10:
                freshness_score = 80.0
            elif max_week >= 5:
                freshness_score = 60.0
            else:
                freshness_score = 40.0
        breakdown["data_freshness"] = {
            "score": freshness_score,
            "weight": self.WEIGHT_DATA_FRESHNESS,
            "detail": f"Latest week: {max(g.week for g in context.recent_games) if context.recent_games else 'N/A'}",
        }

        # 6. Roster verification (25%) — is the player confirmed on the team?
        if context.roster_verified:
            roster_score = 100.0
            roster_detail = "Roster verified via ESPN"
        elif context.roster_warnings:
            roster_score = 20.0
            roster_detail = f"UNVERIFIED: {context.roster_warnings[0]}"
        else:
            roster_score = 50.0
            roster_detail = "Roster not checked"
        breakdown["roster_verified"] = {
            "score": roster_score,
            "weight": self.WEIGHT_ROSTER_VERIFIED,
            "detail": roster_detail,
        }

        # Compute weighted total
        total = sum(
            item["score"] * item["weight"]
            for item in breakdown.values()
        )

        return DataQualityScore(total=round(total, 1), breakdown=breakdown)
