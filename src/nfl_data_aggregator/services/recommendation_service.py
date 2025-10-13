from typing import Optional, List
import logging
from ..models import Matchup, FeatureSet, Recommendation, RawModelResponse
from ..adapters import sportsdata, odds_api
from ..clients.google_genai_client import GoogleGenAIClient
from ..config.config import settings

logger = logging.getLogger(__name__)


def build_features(matchup: Matchup) -> FeatureSet:
    """Gather features from adapters to create a FeatureSet.

    This is intentionally synchronous and simple for the scaffold. In a real
    implementation you'd add caching, retries, async IO, rate-limit handling,
    and richer validation.
    """
    home_stats = sportsdata.fetch_team_stats(matchup.home_team)
    away_stats = sportsdata.fetch_team_stats(matchup.away_team)
    injured = sportsdata.fetch_injured_players(matchup.home_team) + sportsdata.fetch_injured_players(matchup.away_team)
    market_odds = odds_api.fetch_current_odds(matchup.matchup_id)

    features = FeatureSet(
        matchup=matchup,
        home_team_stats=home_stats,
        away_team_stats=away_stats,
        injured_players=injured,
        market_odds=market_odds,
    )
    return features


def _features_to_prompt(features: FeatureSet) -> str:
    """Create a concise prompt for the model from the feature set.

    Keep the prompt deterministic to make parsing easier. This function should
    be iterated on during development to improve model responses.
    """
    lines: List[str] = []
    m = features.matchup
    lines.append(f"Matchup ID: {m.matchup_id}")
    lines.append(f"Home: {m.home_team}")
    lines.append(f"Away: {m.away_team}")
    lines.append("")
    hs = features.home_team_stats
    as_ = features.away_team_stats
    lines.append(f"Home team stats: wins={hs.wins}, points_for={hs.points_for}, defensive_rating={hs.defensive_rating}")
    lines.append(f"Away team stats: wins={as_.wins}, points_for={as_.points_for}, defensive_rating={as_.defensive_rating}")
    lines.append("")
    if features.injured_players:
        lines.append("Injuries:")
        for p in features.injured_players:
            lines.append(f" - {p.player_name} ({p.position}) - snaps_pct={p.snaps_pct}")
        lines.append("")

    if features.market_odds:
        lines.append("Market odds:")
        for o in features.market_odds:
            lines.append(f" - provider={o.provider} spread={o.spread} favorite={o.spread_favorite} ml_home={o.moneyline_home} total={o.total}")
        lines.append("")

    lines.append("Please provide a recommendation for: best spread, best moneyline, best total, and 1-3 player props. Include a short rationale and return results in a simple bullet list with labels.")
    return "\n".join(lines)


def _parse_model_text(raw_text: str, matchup_id: str) -> Recommendation:
    """Parse a model response into a Recommendation using simple heuristics.

    This parser is intentionally permissive and should be replaced with a more
    robust extractor (JSON output from the model, or a structured tool) for
    production.
    """
    best_spread = None
    best_spread_side = None
    best_moneyline = None
    best_total = None
    player_props = []
    rationale_lines = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("- spread:") or low.startswith("spread:"):
            # e.g. "- Spread: Home -3.5"
            try:
                parts = line.split(":", 1)[1].strip().split()
                if len(parts) >= 2:
                    best_spread_side = parts[0]
                    best_spread = float(parts[1].lstrip("+-"))
            except Exception:
                continue
        elif low.startswith("- moneyline:") or low.startswith("moneyline:"):
            # e.g. "- Moneyline: Home -180"
            try:
                parts = line.split(":", 1)[1].strip().split()
                if len(parts) >= 2:
                    # prefer which side
                    best_moneyline = parts[0] + " " + parts[1]
            except Exception:
                continue
        elif low.startswith("- total:") or low.startswith("total:"):
            # e.g. "- Total: 44.5 (Over)"
            try:
                inner = line.split(":", 1)[1].strip().split()[0]
                best_total = float(inner.strip().strip("()"))
            except Exception:
                continue
        elif low.startswith("- player props:") or low.startswith("player props:"):
            # following lines may include props, but for simplicity try to parse inline
            try:
                parts = line.split(":", 1)[1].strip()
                if parts:
                    player_props.append({"text": parts})
            except Exception:
                continue
        else:
            # collect lines for rationale if they look like rationale
            if any(k in low for k in ("rationale", "because", "due to", "advantage")):
                rationale_lines.append(line)

    rationale = " ".join(rationale_lines) if rationale_lines else None

    return Recommendation(
        matchup_id=matchup_id,
        best_spread=best_spread,
        best_spread_side=best_spread_side,
        best_moneyline=best_moneyline,
        best_total=best_total,
        player_props=player_props,
        rationale=rationale,
    )


class RecommendationService:
    def __init__(self, client: Optional[GoogleGenAIClient] = None):
        self.client = client or GoogleGenAIClient(api_key=settings.GOOGLE_GENAI_API_KEY, model=settings.GOOGLE_GENAI_MODEL)

    def recommend_for_matchup(self, matchup: Matchup) -> RawModelResponse:
        features = build_features(matchup)
        prompt = _features_to_prompt(features)
        resp = self.client.generate_text(prompt=prompt, temperature=0.0, max_output_tokens=512)
        raw = resp.get("raw_text", "")
        try:
            parsed = _parse_model_text(raw, matchup.matchup_id)
        except Exception:
            parsed = None
        return RawModelResponse(raw_text=raw, parsed=parsed)
