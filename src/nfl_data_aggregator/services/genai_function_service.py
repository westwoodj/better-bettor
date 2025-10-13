from typing import Any, Optional
import logging
from datetime import datetime, timezone

from ..clients.google_genai_client import GoogleGenAIClient
from ..adapters.espn_api import NFLClient
from .depthchart_service import DepthChartService

logger = logging.getLogger(__name__)


class GenAIFunctionService:
    """Service that accepts a natural language prompt, asks the model with
    function-calling enabled, and invokes local functions (currently: get_depth_chart).

    Usage:
        svc = GenAIFunctionService()
        df = svc.handle_request("get Cardinals depth chart")
    """

    # Define a minimal function schema description (not used by the mocked client,
    # but useful for real clients that accept a functions schema)
    FUNCTIONS_SCHEMA = [
        {
            "name": "get_depth_chart",
            "description": "Return the depth chart for an NFL team",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {"type": "string", "description": "Common team name or abbreviation"},
                    "year": {"type": "integer", "description": "Season year (YYYY)"},
                },
                "required": ["team_name"],
            },
        }
    ]

    def __init__(self, client: Optional[GoogleGenAIClient] = None, nfl_client: Optional[NFLClient] = None):
        self.client = client or GoogleGenAIClient()
        self.nfl = nfl_client or NFLClient()
        self.depthsvc = DepthChartService(self.nfl)

    def handle_request(self, prompt: str, *, force: bool = False) -> Any:
        """Process a user prompt. If the model requests `get_depth_chart`, call it
        and return a pandas DataFrame representing the depth chart.

        If no function call is produced, returns the textual model response.
        """
        resp = self.client.call_with_functions(prompt=prompt, functions=self.FUNCTIONS_SCHEMA)
        # If model returned a function call, execute it
        func = resp.get("function_call")
        if not func:
            return resp.get("raw_text")

        name = func.get("name")
        args = func.get("arguments") or {}

        if name == "get_depth_chart":
            team_name = args.get("team_name") or args.get("team") or args.get("teamName")
            year = args.get("year")
            if not team_name:
                raise ValueError("function call did not include a team_name")
            if year is None:
                year = datetime.now(timezone.utc).year
            try:
                # Fetch raw depth chart JSON
                data = self.nfl.depth_chart_for_team_name(team_name=team_name, year=year, force=force)
            except Exception as exc:
                logger.exception("Error fetching depth chart for %s (%s): %s", team_name, year, exc)
                raise

            # Parse into per-schema DataFrames using DepthChartService
            parsed = self.depthsvc.parse_depthchart(data=data, team_id=self.nfl.find_team_id(team_name) or None, year=year, force=force)
            return parsed

        # unknown function: return raw
        return resp.get("raw_text")
