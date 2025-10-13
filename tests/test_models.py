from src.nfl_data_aggregator.models import Matchup
from src.nfl_data_aggregator.services.recommendation_service import RecommendationService


def test_matchup_and_recommendation_flow():
    matchup = Matchup(matchup_id="test-1", home_team="A", away_team="B")
    svc = RecommendationService()
    resp = svc.recommend_for_matchup(matchup)

    # Basic assertions about the mocked/generated output
    assert resp.raw_text is not None
    # parsed may be None if parsing failed, but raw_text should contain "Recommendation" in the scaffold mock
    assert "Recommendation" in resp.raw_text or resp.parsed is not None

