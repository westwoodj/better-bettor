"""High-level prediction service wrapping the pipeline."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..config.config import settings
from ..db.engine import get_session_factory, init_db
from ..db.repository import PlayerRepo
from ..pipeline.prediction_pipeline import PredictionPipeline, PredictionResult

logger = logging.getLogger(__name__)


class PredictionService:
    """Public API for running player predictions."""

    def __init__(self, session: Session | None = None):
        if session is not None:
            self.session = session
            self._owns_session = False
        else:
            init_db()
            factory = get_session_factory()
            self.session = factory()
            self._owns_session = True

        self._dspy_initialized = False

    def _ensure_dspy(self):
        """Initialize DSPy on first use."""
        if not self._dspy_initialized:
            from ..clients.dspy_client import init_dspy
            init_dspy(
                provider=settings.DSPY_LM_PROVIDER,
                model=settings.DSPY_MODEL,
                temperature=settings.DSPY_TEMPERATURE_ANALYSIS,
            )
            self._dspy_initialized = True

    def predict_player(self, player_id: str, game_id: str) -> PredictionResult:
        """Run prediction pipeline for a player by ID."""
        self._ensure_historical_data(game_id)
        self._ensure_dspy()
        pipeline = PredictionPipeline(self.session)
        result = pipeline.predict(player_id, game_id)
        if self._owns_session:
            self.session.close()
        return result

    def _ensure_historical_data(self, game_id: str) -> dict:
        """Ensure both teams have prior-week data before prediction context assembly."""
        from ..ingestion.espn_ingestor import ESPNIngestor

        try:
            result = ESPNIngestor(self.session).ensure_historical_data(game_id)
            if result["weeks_ingested"]:
                logger.info(
                    "Backfilled ESPN history for game %s: weeks=%s",
                    game_id,
                    result["weeks_ingested"],
                )
            return result
        except Exception:
            # Preserve the existing prediction degradation behavior if ESPN is
            # temporarily unavailable; context assembly will expose any gaps.
            logger.exception("Failed to ensure historical ESPN data for game %s", game_id)
            return {"game_id": game_id, "weeks_ingested": [], "error": True}

    def predict_player_by_name(
        self, name: str, game_id: Optional[str] = None
    ) -> PredictionResult:
        """Run prediction pipeline for a player by name.

        If game_id is not provided, attempts to find the next upcoming game
        for the player's team.
        """
        self._ensure_dspy()
        player_repo = PlayerRepo(self.session)

        player = player_repo.find_by_name(name)
        if player is None:
            player = player_repo.find_by_name_fuzzy(name)
        if player is None:
            raise ValueError(f"Player not found: {name}")

        if game_id is None:
            from ..db.repository import GameRepo
            game_repo = GameRepo(self.session)
            games = game_repo.find_by_team(player.team, settings.NFL_SEASON)
            if not games:
                raise ValueError(f"No games found for team {player.team} in season {settings.NFL_SEASON}")
            # Pick the latest game
            games.sort(key=lambda g: g.week)
            game_id = games[-1].game_id

        pipeline = PredictionPipeline(self.session)
        result = pipeline.predict(player.player_id, game_id)
        if self._owns_session:
            self.session.close()
        return result
