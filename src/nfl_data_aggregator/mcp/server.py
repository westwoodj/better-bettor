"""Local stdio MCP server for the Gridiron Oracle verified data layer."""

import logging
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..db.engine import get_session_factory, init_db
from .schemas import (
    CacheStatusResult,
    GameContextResult,
    GamesResult,
    PlayerPerformancesResult,
    PlayerSearchResult,
    RosterResult,
)
from ..services.data_query_service import DataQueryError, DataQueryService

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Gridiron Oracle NFL Data",
    instructions=(
        "Query the verified NFL database. Reads are cache-only unless a tool's "
        "force argument is explicitly true. Forced calls refresh a bounded ESPN "
        "resource and persist it before returning."
    ),
)


def _execute(operation: Callable[[DataQueryService], Any]) -> Any:
    factory = get_session_factory()
    session = factory()
    try:
        return operation(DataQueryService(session))
    except DataQueryError as exc:
        raise ValueError(str(exc)) from None
    finally:
        session.close()


@mcp.tool()
def get_cache_status() -> CacheStatusResult:
    """Report database identity, record counts, cached seasons/weeks, and domains."""
    return _execute(lambda service: service.get_cache_status())


@mcp.tool()
def search_players(
    query: str,
    team: str | None = None,
    position: str | None = None,
    limit: int = 25,
) -> PlayerSearchResult:
    """Search cached players by partial name, with optional team/position filters."""
    return _execute(
        lambda service: service.search_players(
            query, team=team, position=position, limit=limit
        )
    )


@mcp.tool()
def get_player_performances(
    player_id: str,
    season: int | None = None,
    limit: int = 20,
    force: bool = False,
) -> PlayerPerformancesResult:
    """Get cached player game logs; force refreshes the requested ESPN season."""
    return _execute(
        lambda service: service.get_player_performances(
            player_id, season=season, limit=limit, force=force
        )
    )


@mcp.tool()
def list_games(
    season: int,
    week: int | None = None,
    team: str | None = None,
    limit: int = 50,
    force: bool = False,
) -> GamesResult:
    """List cached schedules/outcomes; force requires and refreshes one league week."""
    return _execute(
        lambda service: service.list_games(
            season, week=week, team=team, limit=limit, force=force
        )
    )


@mcp.tool()
def get_game_context(game_id: str, force: bool = False) -> GameContextResult:
    """Get teams, outcome, kickoff, venue/location, weather, and defense context."""
    return _execute(lambda service: service.get_game_context(game_id, force=force))


@mcp.tool()
def get_roster(
    team: str,
    include_all_positions: bool = False,
    force: bool = False,
) -> RosterResult:
    """Get a cached roster; default to skill positions or request the full roster."""
    return _execute(
        lambda service: service.get_roster(
            team,
            include_all_positions=include_all_positions,
            force=force,
        )
    )


def main() -> None:
    """Initialize tables and run the MCP server over stdio."""
    init_db()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
