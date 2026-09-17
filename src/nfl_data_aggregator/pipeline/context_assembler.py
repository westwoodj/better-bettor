"""Stage 1: Deterministic context assembly from database.

Queries all repositories and computes season averages to build a
PredictionContext for the DSPy pipeline stages.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..db.repository import (
    PlayerRepo, GameRepo, StatsRepo, PropLineRepo, DefenseProfileRepo,
)
from ..db.sa_models import Game
from .context_models import (
    PredictionContext, PlayerProfile, GameStats, SeasonAverages,
    MatchupContext, GameEnvironment, PropLineContext,
)

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles a PredictionContext from database data."""

    def __init__(self, session: Session, espn_client=None):
        self.session = session
        self.player_repo = PlayerRepo(session)
        self.game_repo = GameRepo(session)
        self.stats_repo = StatsRepo(session)
        self.prop_repo = PropLineRepo(session)
        self.defense_repo = DefenseProfileRepo(session)
        self._espn_client = espn_client

    def assemble(self, player_id: str, game_id: str) -> PredictionContext:
        """Build a full PredictionContext for a player and upcoming game."""
        # Player profile
        player_row = self.player_repo.get(player_id)
        if player_row is None:
            raise ValueError(f"Player not found: {player_id}")

        profile = PlayerProfile(
            player_id=player_row.player_id,
            name=player_row.name,
            team=player_row.team or "",
            position=player_row.position or "",
            status=player_row.status or "active",
            height=player_row.height or "",
            weight=player_row.weight,
            experience=player_row.experience,
        )

        # Game info
        game_row = self.game_repo.get(game_id)
        if game_row is None:
            raise ValueError(f"Game not found: {game_id}")

        # Determine opponent and home/away
        if game_row.home_team == player_row.team:
            opponent = game_row.away_team
            home_away = "home"
        else:
            opponent = game_row.home_team
            home_away = "away"

        # Recent game stats
        season = game_row.season
        all_stats = self.stats_repo.get_player_games(player_id, season=season)
        recent_games = []
        for stat in all_stats:
            game = self.game_repo.get(stat.game_id)
            if game is None:
                continue
            opp = game.away_team if game.home_team == player_row.team else game.home_team
            recent_games.append(GameStats(
                game_id=stat.game_id,
                week=game.week,
                season=game.season,
                opponent=opp,
                pass_completions=stat.pass_completions,
                pass_attempts=stat.pass_attempts,
                pass_yards=stat.pass_yards,
                pass_tds=stat.pass_tds,
                interceptions=stat.interceptions,
                passer_rating=stat.passer_rating,
                rush_attempts=stat.rush_attempts,
                rush_yards=stat.rush_yards,
                rush_tds=stat.rush_tds,
                receptions=stat.receptions,
                targets=stat.targets,
                receiving_yards=stat.receiving_yards,
                receiving_tds=stat.receiving_tds,
                fumbles=stat.fumbles,
                fantasy_points=stat.fantasy_points,
                source=stat.source or "",
            ))

        # Sort by week
        recent_games.sort(key=lambda g: g.week)

        # Season averages
        averages = self._compute_averages(recent_games)

        # Matchup context (defense profile)
        matchup = self._build_matchup(game_id, opponent, home_away, season, game_row.week)

        # Game environment
        environment = GameEnvironment(
            venue=game_row.venue or "",
            game_type=game_row.game_type or "regular",
        )
        if game_row.weather_conditions:
            environment.weather_temp = game_row.weather_conditions.get("temp")
            environment.weather_wind = game_row.weather_conditions.get("wind")

        # Prop lines
        prop_rows = self.prop_repo.get_for_player_game(player_id, game_id)
        prop_lines = [
            PropLineContext(
                market=p.market,
                line_value=p.line_value,
                over_odds=p.over_odds,
                under_odds=p.under_odds,
                sportsbook=p.sportsbook or "",
            )
            for p in prop_rows
        ]

        # Roster verification
        roster_verified, roster_warnings = self._verify_roster(
            player_row.name, player_row.espn_id, player_row.team, game_row
        )

        return PredictionContext(
            player=profile,
            recent_games=recent_games,
            season_averages=averages,
            matchup=matchup,
            environment=environment,
            prop_lines=prop_lines,
            roster_verified=roster_verified,
            roster_warnings=roster_warnings,
        )

    def _compute_averages(self, games: list[GameStats]) -> SeasonAverages:
        """Compute season averages from game stats."""
        n = len(games)
        if n == 0:
            return SeasonAverages()

        def _sum(attr):
            return sum(getattr(g, attr) or 0 for g in games)

        return SeasonAverages(
            games_played=n,
            avg_pass_yards=_sum("pass_yards") / n,
            avg_pass_tds=_sum("pass_tds") / n,
            avg_rush_yards=_sum("rush_yards") / n,
            avg_rush_tds=_sum("rush_tds") / n,
            avg_receptions=_sum("receptions") / n,
            avg_receiving_yards=_sum("receiving_yards") / n,
            avg_receiving_tds=_sum("receiving_tds") / n,
            avg_fantasy_points=_sum("fantasy_points") / n,
            total_pass_yards=_sum("pass_yards"),
            total_rush_yards=_sum("rush_yards"),
            total_receiving_yards=_sum("receiving_yards"),
        )

    def _verify_roster(self, player_name: str, espn_id: Optional[str],
                       team: Optional[str], game_row) -> tuple[bool, list[str]]:
        """Verify the player is on a current roster for this game.

        Checks BOTH teams' ESPN rosters (home and away) by ID and name.
        Returns (verified: bool, warnings: list[str]).
        """
        warnings: list[str] = []

        # Basic check: player's team should be in the game
        if team and team not in (game_row.home_team, game_row.away_team):
            warnings.append(
                f"Player team '{team}' does not match either game team "
                f"({game_row.home_team} vs {game_row.away_team})"
            )
            return False, warnings

        if self._espn_client is None:
            warnings.append("Roster not verified (no ESPN client available)")
            return False, warnings

        # Check both teams' rosters
        game_teams = [game_row.home_team, game_row.away_team]
        for check_team in game_teams:
            try:
                team_id = self._resolve_team_id(check_team)
                if team_id is None:
                    continue

                roster_data = self._espn_client.roster(team_id, force=True)
                match = self._find_player_in_roster(
                    roster_data, espn_id, player_name
                )

                if match is not None:
                    matched_id, matched_name, match_type = match
                    if check_team == team:
                        # Found on expected team
                        if match_type == "id":
                            logger.info(
                                "Roster verified: %s (ESPN %s) on %s",
                                player_name, espn_id, check_team,
                            )
                            return True, warnings
                        else:
                            # Name matched but ID differs
                            warnings.append(
                                f"Player '{player_name}' found on {check_team} by name "
                                f"but ESPN ID mismatch: expected {espn_id}, "
                                f"roster has {matched_id} ({matched_name})"
                            )
                            return True, warnings
                    else:
                        # Found on the OTHER team in this game
                        warnings.append(
                            f"Player '{player_name}' found on {check_team} roster "
                            f"(match by {match_type}), but listed as {team} in our data"
                        )
                        return False, warnings

            except Exception as exc:
                logger.warning(
                    "ESPN roster check failed for team %s: %s", check_team, exc
                )

        # Not found on either roster
        warnings.append(
            f"Player '{player_name}' (ESPN ID {espn_id}) NOT found on either "
            f"{game_row.home_team} or {game_row.away_team} ESPN roster"
        )
        return False, warnings

    def _resolve_team_id(self, team_abbr: str) -> Optional[str]:
        """Resolve a team abbreviation to an ESPN team ID."""
        team_obj = self._espn_client.find_team_by_name(team_abbr)
        if team_obj is not None:
            return team_obj.get("id")
        return self._espn_client.find_team_id(team_abbr)

    @staticmethod
    def _find_player_in_roster(
        roster_data, espn_id: Optional[str], player_name: str
    ) -> Optional[tuple[str, str, str]]:
        """Search a roster response for a player by ID or name.

        Returns (matched_id, matched_name, match_type) or None.
        match_type is 'id' or 'name'.
        """
        if not isinstance(roster_data, dict):
            return None

        name_lower = player_name.lower()
        name_match = None

        for group in roster_data.get("athletes", []):
            for entry in group.get("items", []):
                entry_id = str(entry.get("id", ""))
                entry_name = entry.get("displayName", "") or entry.get("fullName", "")

                # ID match is authoritative
                if espn_id and entry_id == str(espn_id):
                    return (entry_id, entry_name, "id")

                # Track name match as fallback
                if entry_name and entry_name.lower() == name_lower:
                    name_match = (entry_id, entry_name, "name")

        return name_match

    def _build_matchup(self, game_id: str, opponent: str, home_away: str,
                       season: int, week: int) -> MatchupContext:
        """Build matchup context from defense profile data."""
        matchup = MatchupContext(
            game_id=game_id,
            opponent=opponent,
            home_away=home_away,
        )

        # Try to get defense profile for the opponent
        profile = self.defense_repo.get_latest(opponent, season)
        if profile:
            matchup.opponent_pass_yards_allowed = profile.pass_yards_allowed
            matchup.opponent_rush_yards_allowed = profile.rush_yards_allowed
            matchup.opponent_points_allowed = profile.points_allowed
            matchup.opponent_pressure_rate = profile.pressure_rate

        return matchup
