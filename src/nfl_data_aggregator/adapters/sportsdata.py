from typing import List, Optional
from datetime import date
from ..models import TeamStats, PlayerStats


def fetch_team_stats(team_id: str, season: Optional[int] = None) -> TeamStats:
    """Mock/example fetcher for team-level statistics.

    Replace with a real HTTP call to SportsDataIO, Sportradar, etc.
    """
    # Example mocked stats
    return TeamStats(
        team_id=team_id,
        team_name=f"Team {team_id}",
        season=season or date.today().year,
        wins=8,
        losses=4,
        points_for=320.5,
        points_against=280.2,
        offensive_rating=105.3,
        defensive_rating=98.6,
    )


def fetch_injured_players(team_id: str) -> List[PlayerStats]:
    """Return a small list of injured players (mock)."""
    return [
        PlayerStats(
            player_id=f"{team_id}-p1",
            player_name="John Doe",
            team_id=team_id,
            position="RB",
            season=date.today().year,
            fantasy_points=45.3,
            snaps_pct=0.0,
        )
    ]
