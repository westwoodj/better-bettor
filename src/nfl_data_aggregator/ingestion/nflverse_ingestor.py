"""Ingest nflverse data (via nfl_data_py) into the database."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..adapters.nflverse_adapter import NflverseAdapter
from ..db.repository import PlayerRepo, GameRepo, StatsRepo, DefenseProfileRepo

logger = logging.getLogger(__name__)


class NflverseIngestor:
    """Fetches nflverse data and persists players, games, stats, and defense profiles."""

    def __init__(self, session: Session, adapter: NflverseAdapter | None = None):
        self.session = session
        self.adapter = adapter or NflverseAdapter()
        self.player_repo = PlayerRepo(session)
        self.game_repo = GameRepo(session)
        self.stats_repo = StatsRepo(session)
        self.defense_repo = DefenseProfileRepo(session)

    def ingest_season(self, season: int) -> dict:
        """Ingest full season of player stats and schedule from nflverse."""
        counts = {"players": 0, "games": 0, "stats": 0}

        # Import schedule / games
        games = self.adapter.import_schedule([season])
        for g in games:
            gid = g.pop("game_id", None)
            if not gid:
                continue
            self.game_repo.upsert(gid, **g)
            counts["games"] += 1

        # Import rosters for player info
        rosters = self.adapter.import_rosters([season])
        # Build nflverse_id -> player mapping for cross-referencing
        nflverse_map = {}
        for r in rosters:
            nflverse_id = r.get("nflverse_id")
            name = r.get("name", "")
            team = r.get("team", "")

            # Try to find existing player by name + team
            existing = self.player_repo.find_by_name(name)
            if existing:
                existing.nflverse_id = nflverse_id
                if r.get("status"):
                    existing.status = r["status"]
                nflverse_map[nflverse_id] = existing.player_id
            else:
                # Create new player with nflverse_id as player_id
                pid = nflverse_id or name.replace(" ", "_").lower()
                self.player_repo.upsert(
                    pid,
                    nflverse_id=nflverse_id,
                    name=name,
                    team=team,
                    position=r.get("position"),
                    status=r.get("status"),
                    height=r.get("height"),
                    weight=r.get("weight"),
                    experience=r.get("experience"),
                )
                nflverse_map[nflverse_id] = pid
                counts["players"] += 1

        # Import weekly stats
        weekly = self.adapter.import_weekly_data([season])
        for w in weekly:
            nflverse_id = w.get("nflverse_id")
            player_id = nflverse_map.get(nflverse_id)
            if not player_id:
                # Fallback: use nflverse_id itself
                player_id = nflverse_id
                if not player_id:
                    continue
                # Ensure player exists
                self.player_repo.upsert(
                    player_id,
                    nflverse_id=nflverse_id,
                    name=w.get("name", ""),
                    team=w.get("team", ""),
                    position=w.get("position"),
                )

            # Find game_id for this week
            week_num = w.get("week")
            game_id = self._find_game_id(w.get("team", ""), season, week_num)
            if not game_id:
                game_id = f"{season}_{week_num}_{w.get('team', 'UNK')}"

            stat_data = {k: v for k, v in w.items()
                         if k not in ("nflverse_id", "name", "team", "position", "week", "season", "source")
                         and v is not None}
            stat_data["source"] = "nflverse"

            self.stats_repo.upsert(player_id, game_id, **stat_data)
            counts["stats"] += 1

        self.session.commit()
        logger.info("nflverse ingest season %d: %s", season, counts)
        return counts

    def compute_defense_profiles(self, season: int, through_week: int) -> int:
        """Aggregate opponent stats to build defense profiles through a given week.

        Returns count of profiles created/updated.
        """
        from sqlalchemy import select, func
        from ..db.sa_models import Game, PlayerGameStats

        count = 0
        # Get all teams that played
        games = self.game_repo.find_by_week(season, 1)  # Start from any week to get teams
        teams = set()
        all_games = []
        for wk in range(1, through_week + 1):
            week_games = self.game_repo.find_by_week(season, wk)
            all_games.extend(week_games)
            for g in week_games:
                teams.add(g.home_team)
                teams.add(g.away_team)

        for team in teams:
            # Collect stats of opponents who played against this team
            total_pass_yds = 0.0
            total_rush_yds = 0.0
            total_points = 0.0
            game_count = 0

            for g in all_games:
                if g.home_team == team or g.away_team == team:
                    game_count += 1
                    # Opponent stats from game
                    opponent_team = g.away_team if g.home_team == team else g.home_team
                    opp_stats = self.session.execute(
                        select(PlayerGameStats).where(
                            PlayerGameStats.game_id == g.game_id,
                        ).join(
                            # Only include opponent players
                            # Since we don't have team on stats, use player table
                            PlayerGameStats.player
                        )
                    ).scalars().all()

                    for s in opp_stats:
                        if s.player and s.player.team == opponent_team:
                            total_pass_yds += (s.pass_yards or 0)
                            total_rush_yds += (s.rush_yards or 0)

                    # Parse score for points allowed
                    if g.final_score:
                        try:
                            parts = g.final_score.split("-")
                            if g.home_team == team:
                                total_points += float(parts[1])  # away score = points allowed
                            else:
                                total_points += float(parts[0])  # home score = points allowed
                        except (ValueError, IndexError):
                            pass

            if game_count > 0:
                self.defense_repo.upsert(
                    team=team,
                    season=season,
                    week_through=through_week,
                    source="nflverse",
                    pass_yards_allowed=total_pass_yds / game_count,
                    rush_yards_allowed=total_rush_yds / game_count,
                    points_allowed=total_points / game_count,
                )
                count += 1

        self.session.commit()
        logger.info("Defense profiles computed for %d teams through week %d", count, through_week)
        return count

    def _find_game_id(self, team: str, season: int, week: Optional[int]) -> Optional[str]:
        """Find a game_id for a team in a specific week."""
        if week is None:
            return None
        games = self.game_repo.find_by_week(season, week)
        for g in games:
            if g.home_team == team or g.away_team == team:
                return g.game_id
        return None
