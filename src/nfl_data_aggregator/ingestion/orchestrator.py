"""Orchestrator to run all ingestors for full season or weekly updates."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.engine import get_session_factory, init_db
from ..db.sa_models import Player
from ..db.repository import StatsRepo
from .espn_ingestor import ESPNIngestor
from .nflverse_ingestor import NflverseIngestor

logger = logging.getLogger(__name__)


class IngestionOrchestrator:
    """Coordinates running all data ingestors."""

    def __init__(self, session: Session | None = None):
        if session is not None:
            self.session = session
            self._owns_session = False
        else:
            init_db()
            factory = get_session_factory()
            self.session = factory()
            self._owns_session = True

    def run_full_season(self, season: int, max_week: int = 18) -> dict:
        """Ingest a full season of data from all sources."""
        summary = {"nflverse": {}, "espn": {}, "defense_profiles": 0}

        # 1. nflverse data first (bulk import)
        logger.info("Starting nflverse ingestion for season %d", season)
        nflverse = NflverseIngestor(self.session)
        summary["nflverse"] = nflverse.ingest_season(season)

        # 2. ESPN data (week by week)
        logger.info("Starting ESPN ingestion for season %d", season)
        espn = ESPNIngestor(self.session)
        espn_totals = {"games": 0, "players": 0, "stats": 0}
        for week in range(1, max_week + 1):
            try:
                result = espn.ingest_week(season, week)
                for k in espn_totals:
                    espn_totals[k] += result.get(k, 0)
            except Exception:
                logger.exception("ESPN ingestion failed for week %d", week)
        summary["espn"] = espn_totals

        # 3. Defense profiles
        logger.info("Computing defense profiles through week %d", max_week)
        summary["defense_profiles"] = nflverse.compute_defense_profiles(season, max_week)

        if self._owns_session:
            self.session.close()

        logger.info("Full season ingestion complete: %s", summary)
        return summary

    def run_weekly_update(self, season: int, week: int) -> dict:
        """Ingest data for a single week from all sources."""
        summary = {"espn": {}, "nflverse_stats": 0, "defense_profiles": 0}

        # ESPN for current week
        espn = ESPNIngestor(self.session)
        summary["espn"] = espn.ingest_week(season, week)

        # nflverse weekly stats
        nflverse = NflverseIngestor(self.session)
        weekly = nflverse.adapter.get_player_weekly_stats(season, week)
        stats_repo = StatsRepo(self.session)

        for w in weekly:
            nflverse_id = w.get("nflverse_id")
            if not nflverse_id:
                continue

            player = self.session.execute(
                select(Player).where(Player.nflverse_id == nflverse_id)
            ).scalar_one_or_none()

            if player:
                game_id = nflverse._find_game_id(player.team, season, week)
                if game_id:
                    stat_data = {k: v for k, v in w.items()
                                 if k not in ("nflverse_id", "name", "team", "position", "week", "season", "source")
                                 and v is not None}
                    stat_data["source"] = "nflverse"
                    stats_repo.upsert(player.player_id, game_id, **stat_data)
                    summary["nflverse_stats"] += 1

        self.session.commit()

        # Update defense profiles
        summary["defense_profiles"] = nflverse.compute_defense_profiles(season, week)

        if self._owns_session:
            self.session.close()

        logger.info("Weekly update for week %d complete: %s", week, summary)
        return summary
