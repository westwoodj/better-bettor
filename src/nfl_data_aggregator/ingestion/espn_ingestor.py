"""Ingest ESPN rosters, games, and player statistics into the database."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.espn_api import NFLClient
from ..adapters.espn_stats_adapter import ESPNStatsAdapter, SKILL_POSITIONS
from ..db.repository import GameRepo, PlayerRepo, StatsRepo
from ..db.sa_models import Player, PlayerGameStats

logger = logging.getLogger(__name__)


class ESPNIngestor:
    """Fetch ESPN data and persist normalized players, games, and stats."""

    def __init__(self, session: Session, client: NFLClient | None = None):
        self.session = session
        self.client = client or NFLClient()
        self.adapter = ESPNStatsAdapter(self.client)
        self.player_repo = PlayerRepo(session)
        self.game_repo = GameRepo(session)
        self.stats_repo = StatsRepo(session)

    def ingest_roster(
        self,
        team_id: str,
        force: bool = False,
        *,
        include_all_positions: bool = False,
        reconcile: bool = False,
        commit: bool = True,
    ) -> dict:
        """Fetch and persist an ESPN roster.

        Reconciliation only clears players in the requested position scope, so
        a skill-position refresh cannot accidentally remove cached defenders.
        """
        roster = self.client.roster(team_id, force=force)
        team = roster.get("team", {}) if isinstance(roster, dict) else {}
        team_abbr = str(team.get("abbreviation", "")).upper()
        if not team_abbr:
            team_info = self.client.find_team_by_name(team_id)
            team_abbr = str((team_info or {}).get("abbreviation", "")).upper()
        if not team_abbr:
            raise ValueError(f"ESPN roster response did not identify team {team_id}")

        players = self.adapter.extract_players_from_roster(
            roster,
            team_abbr,
            include_all_positions=include_all_positions,
        )
        fetched_ids: set[str] = set()
        for player_data in players:
            data = dict(player_data)
            player_id = data.pop("player_id")
            fetched_ids.add(player_id)
            self.player_repo.upsert(player_id, **data)

        reconciled = 0
        if reconcile:
            for cached in self.player_repo.list_by_team(team_abbr):
                in_scope = include_all_positions or cached.position in SKILL_POSITIONS
                if in_scope and cached.player_id not in fetched_ids:
                    cached.team = None
                    reconciled += 1

        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return {"team": team_abbr, "players": len(players), "reconciled": reconciled}

    def ingest_game(
        self,
        game_id: str,
        force: bool = False,
        *,
        summary_data: dict | None = None,
        base_game_data: dict | None = None,
        commit: bool = True,
    ) -> dict:
        """Fetch and normalize one ESPN event summary."""
        summary = summary_data
        if summary is None:
            summary = self.client.event_summary(game_id, force=force)
        if not isinstance(summary, dict):
            raise ValueError(f"ESPN returned an invalid event summary for game {game_id}")

        parsed_game = self.adapter.extract_game_from_event_summary(summary, game_id) or {}
        game_data = {key: value for key, value in parsed_game.items() if value is not None}
        game_data.update({
            key: value for key, value in (base_game_data or {}).items() if value is not None
        })
        game_data["game_id"] = str(game_data.get("game_id") or game_id)
        self._upsert_game(game_data)

        player_infos = self.adapter.extract_player_info_from_summary(summary)
        for player_data in player_infos:
            data = dict(player_data)
            player_id = data.pop("player_id")
            self.player_repo.upsert(player_id, **data)

        stat_entries = self.adapter.extract_stats_from_event_summary(summary, game_id)
        for stat_data in stat_entries:
            data = dict(stat_data)
            player_id = data.pop("player_id")
            stat_game_id = data.pop("game_id")
            self.stats_repo.upsert(player_id, stat_game_id, **data)

        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return {"games": 1, "players": len(player_infos), "stats": len(stat_entries)}

    def ingest_player_season(
        self,
        player_id: str,
        season: int,
        *,
        force: bool = False,
        commit: bool = True,
    ) -> dict:
        """Refresh all event summaries referenced by an ESPN player gamelog."""
        player = self.player_repo.get(player_id)
        if player is None:
            raise ValueError(f"Player {player_id} not found")
        espn_id = player.espn_id or player.player_id
        gamelog = self.client.player_gamelog(espn_id, season, force=force)
        if not isinstance(gamelog, dict):
            raise ValueError(f"ESPN returned an invalid gamelog for player {player_id}")
        game_ids = self.adapter.extract_game_ids_from_gamelog(gamelog)
        if not game_ids:
            raise ValueError(f"No ESPN games found for player {player_id} in {season}")

        totals = {"games": 0, "players": 0, "stats": 0}
        for game_id in game_ids:
            result = self.ingest_game(game_id, force=force, commit=False)
            for key in totals:
                totals[key] += result[key]
        if commit:
            self.session.commit()
        totals["gamelog_games"] = len(game_ids)
        return totals

    def ensure_historical_data(self, game_id: str) -> dict:
        """Backfill missing prior-week ESPN data for both teams in a game."""
        game = self.game_repo.get(game_id)
        if game is None:
            raise ValueError(f"Game not found: {game_id}")

        teams = (game.home_team, game.away_team)
        weeks_ingested: list[int] = []
        results: dict[int, dict] = {}
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
        stmt = (
            select(PlayerGameStats.player_id)
            .join(Player, Player.player_id == PlayerGameStats.player_id)
            .where(PlayerGameStats.game_id == game_id, Player.team == team)
            .limit(1)
        )
        return self.session.execute(stmt).first() is not None

    def ingest_week(
        self,
        season: int,
        week: int,
        force: bool = False,
        *,
        strict: bool = False,
        commit: bool = True,
    ) -> dict:
        """Ingest a single regular-season week from ESPN."""
        counts = {"games": 0, "players": 0, "stats": 0}
        try:
            scoreboard = self.client.scoreboard(
                dates=str(season), week=week, seasontype=2, force=force
            )
        except Exception:
            if strict:
                raise
            logger.exception("Failed to fetch ESPN scoreboard for week %d", week)
            return counts

        games = self.adapter.extract_games_from_scoreboard(scoreboard)
        for raw_game in games:
            game_data = dict(raw_game)
            game_data["season"] = season
            game_data["week"] = week
            game_id = str(game_data["game_id"])
            try:
                summary = self.client.event_summary(game_id, force=force)
                result = self.ingest_game(
                    game_id,
                    force=force,
                    summary_data=summary,
                    base_game_data=game_data,
                    commit=False,
                )
                for key in counts:
                    counts[key] += result[key]
            except Exception:
                if strict:
                    raise
                logger.exception("Failed to ingest ESPN game %s", game_id)

        if commit:
            self.session.commit()
        logger.info("ESPN ingest week %d: %s", week, counts)
        return counts

    def _upsert_game(self, game_data: dict[str, Any]) -> None:
        data = dict(game_data)
        game_id = str(data.pop("game_id"))
        existing = self.game_repo.get(game_id)

        kickoff = _parse_datetime(data.get("kickoff_time"))
        if kickoff is not None:
            data["kickoff_time"] = kickoff
        else:
            data.pop("kickoff_time", None)

        if existing is not None:
            data = {
                key: value for key, value in data.items()
                if value is not None and not (key in {"season", "week"} and value == 0)
            }
        else:
            required = ("season", "week", "home_team", "away_team")
            missing = [key for key in required if data.get(key) in (None, "", 0)]
            if missing:
                raise ValueError(
                    f"ESPN game {game_id} is missing required fields: {', '.join(missing)}"
                )
        self.game_repo.upsert(game_id, **data)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Could not parse ESPN kickoff time %r", value)
        return None
