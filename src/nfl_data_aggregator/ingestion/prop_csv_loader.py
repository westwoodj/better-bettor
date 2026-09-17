"""Load prop line data from CSV files into the database."""

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from ..db.repository import PlayerRepo, PropLineRepo

logger = logging.getLogger(__name__)


class PropCSVLoader:
    """Parse CSV files containing player prop lines and insert into prop_lines table.

    Expected CSV columns: player_name, market, line_value, over_odds, under_odds, sportsbook
    Optional columns: game_id, consensus_line
    """

    def __init__(self, session: Session):
        self.session = session
        self.player_repo = PlayerRepo(session)
        self.prop_repo = PropLineRepo(session)

    def load_file(self, path: str | Path, game_id: str | None = None) -> dict:
        """Load a CSV file of prop lines.

        Args:
            path: Path to the CSV file.
            game_id: Optional default game_id to assign to all rows.

        Returns:
            Summary dict with counts: loaded, skipped, errors.
        """
        path = Path(path)
        counts = {"loaded": 0, "skipped": 0, "errors": 0}

        try:
            with path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        player_name = row.get("player_name", "").strip()
                        if not player_name:
                            counts["skipped"] += 1
                            continue

                        # Fuzzy match player name to player_id
                        player = self.player_repo.find_by_name_fuzzy(player_name)
                        if player is None:
                            logger.warning("No player match for '%s', skipping", player_name)
                            counts["skipped"] += 1
                            continue

                        market = row.get("market", "").strip()
                        line_value = _safe_float(row.get("line_value"))
                        if not market or line_value is None:
                            counts["skipped"] += 1
                            continue

                        self.prop_repo.add(
                            player_id=player.player_id,
                            game_id=row.get("game_id") or game_id,
                            market=market,
                            line_value=line_value,
                            over_odds=_safe_float(row.get("over_odds")),
                            under_odds=_safe_float(row.get("under_odds")),
                            sportsbook=row.get("sportsbook", "").strip() or None,
                            consensus_line=_safe_float(row.get("consensus_line")),
                        )
                        counts["loaded"] += 1

                    except Exception:
                        logger.exception("Error processing CSV row: %s", row)
                        counts["errors"] += 1

        except FileNotFoundError:
            logger.error("CSV file not found: %s", path)
            counts["errors"] += 1
            return counts

        self.session.commit()
        logger.info("Prop CSV load from %s: %s", path, counts)
        return counts


def _safe_float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
