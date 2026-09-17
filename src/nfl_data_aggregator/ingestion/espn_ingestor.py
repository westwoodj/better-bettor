"""Ingest ESPN scoreboard and event summary data into the database."""

import logging

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..adapters.espn_api import NFLClient
from ..adapters.espn_stats_adapter import ESPNStatsAdapter
from ..db.repository import PlayerRepo, GameRepo, StatsRepo
from ..db.sa_models import Player, PlayerGameStats

logger = logging.getLogger(__name__)


class ESPNIngestor:
    """Fetches ESPN data and persists players, games, and stats to the DB."""

    def __init__(self, session: Session, client: NFLClient | None = None):
        self.session = session
        self.client = client or NFLClient()
        self.adapter = ESPNStatsAdapter(self.client)
        self.player_repo = PlayerRepo(session)
        self.game_repo = GameRepo(session)
        self.stats_repo = StatsRepo(session)

    def ingest_roster(self, team_id: str, force: bool = False) -> dict:
        """Fetch and persist the current ESPN skill-position roster."""
        roster = self.client.roster(team_id, force=force)
        team = roster.get("team", {}) if isinstance(roster, dict) else {}
        team_abbr = team.get("abbreviation", "")
        players = self.adapter.extract_players_from_roster(roster, team_abbr)
        for player in players:
            player_id = player.pop("player_id")
            self.player_repo.upsert(player_id, **player)
        self.session.commit()
        return {"team": team_abbr, "players": len(players)}

    def ensure_historical_data(self, game_id: str) -> dict:
        """Backfill missing prior-week ESPN data for both teams in a game.

        This is intentionally driven by DB completeness: weeks that already
        have a game and at least one stat row for each team are left alone.
        Missing weeks are fetched with ``force=True`` so a prediction never
        relies on an accidental or stale local ESPN payload.
        """
        game = self.game_repo.get(game_id)
        if game is None:
            raise ValueError(f"Game not found: {game_id}")

        teams = (game.home_team, game.away_team)
        weeks_ingested: list[int] = []
        results: dict[int, dict] = {}

        # The target game itself is not historical yet; only prior weeks feed
        # the prediction baseline.
        for week in range(1, game.week):
            week_games = self.game_repo.find_by_week(game.season, week)
            team_games = [
                candidate for candidate in week_games
                if candidate.home_team in teams or candidate.away_team in teams
            ]
            complete = all(
                any(self._has_team_stats(candidate.game_id, team) for candidate in team_games)
                for team in teams
            )
            if complete:
                continue

            weeks_ingested.append(week)
            results[week] = self.ingest_week(game.season, week, force=True)

        return {
            "game_id": game_id,
            "season": game.season,
            "through_week": game.week - 1,
            "weeks_ingested": weeks_ingested,
            "results": results,
        }

    def _has_team_stats(self, game_id: str, team: str) -> bool:
        """Return whether a game has any persisted skill-player stats for team."""
        stmt = (
            select(PlayerGameStats.player_id)
            .join(Player, Player.player_id == PlayerGameStats.player_id)
            .where(
                PlayerGameStats.game_id == game_id,
                Player.team == team,
            )
            .limit(1)
        )
        return self.session.execute(stmt).first() is not None

    def ingest_week(self, season: int, week: int, force: bool = False) -> dict:
        """Ingest a single week of games from ESPN.

        Returns a summary dict with counts of ingested items.
        """
        counts = {"games": 0, "players": 0, "stats": 0}

        # Fetch scoreboard for the week
        try:
            scoreboard = self.client.scoreboard(week=week, seasontype=2, force=force)
        except Exception:
            logger.exception("Failed to fetch ESPN scoreboard for week %d", week)
            return counts

        games = self.adapter.extract_games_from_scoreboard(scoreboard)
        for game_data in games:
            game_data["season"] = season
            game_data["week"] = week
            game_id = game_data.pop("game_id")
            # Convert kickoff_time string to keep as-is (DateTime parsing handled elsewhere)
            kickoff = game_data.pop("kickoff_time", None)
            self.game_repo.upsert(game_id, **game_data)
            counts["games"] += 1

            # Fetch event summary for stats
            try:
                summary = self.client.event_summary(game_id, force=force)
            except Exception:
                logger.exception("Failed to fetch event summary for game %s", game_id)
                continue

            # Extract players
            player_infos = self.adapter.extract_player_info_from_summary(summary)
            for p in player_infos:
                pid = p.pop("player_id")
                self.player_repo.upsert(pid, **p)
                counts["players"] += 1

            # Extract stats
            stat_entries = self.adapter.extract_stats_from_event_summary(summary, game_id)
            for stat in stat_entries:
                pid = stat.pop("player_id")
                gid = stat.pop("game_id")
                self.stats_repo.upsert(pid, gid, **stat)
                counts["stats"] += 1

        self.session.commit()
        logger.info("ESPN ingest week %d: %s", week, counts)
        return counts
