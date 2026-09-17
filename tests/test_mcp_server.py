"""End-to-end stdio contract test for the NFL data MCP server."""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_mcp_stdio_lists_tools_and_returns_concise_validation_error(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'mcp.db').as_posix()}"
    env["PYTHONPATH"] = str(root / "src")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "nfl_data_aggregator.mcp.server"],
        env=env,
    )

    async def exercise():
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listing = await session.list_tools()
                names = {tool.name for tool in listing.tools}
                assert names == {
                    "get_cache_status",
                    "search_players",
                    "get_player_performances",
                    "list_games",
                    "get_game_context",
                    "get_roster",
                }
                cache_tool = next(tool for tool in listing.tools if tool.name == "get_cache_status")
                assert "record_counts" in cache_tool.outputSchema["properties"]
                result = await session.call_tool(
                    "list_games", {"season": 2026, "force": True}
                )
                assert result.isError is True
                text = " ".join(getattr(item, "text", "") for item in result.content)
                assert "week is required" in text

    asyncio.run(exercise())
