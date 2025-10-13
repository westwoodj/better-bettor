from src.nfl_data_aggregator.adapters.espn_api import NFLClient
import json


def test_teams_reads_local_cache():
    """Ensure NFLClient.teams() returns the sample local JSON without network calls."""
    client = NFLClient()

    # By default, there is a sample file under data/espn/football/nfl/all-teams.json
    data = client.teams(force=False)

    assert isinstance(data, dict) or isinstance(data, list)

    # If the sample file is present, it should include the 'sports' key as in the sample
    if isinstance(data, dict):
        assert "sports" in data
        # search teams for a known team from the sample
        text = json.dumps(data)
        assert "Arizona Cardinals" in text or "Cardinals" in text


def test_teams_force_uses_network_monkeypatched():
    """When force=True, the client should perform a network call. We inject a dummy session to avoid real HTTP."""

    client = NFLClient()

    # Replace the session with a dummy one that returns a predictable JSON-like response
    class DummyResp:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        text = '{"dummy": true}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"dummy": True}

    class DummySession:
        def get(self, url, params=None, timeout=None):
            return DummyResp()

    client._session = DummySession()

    data = client.teams(force=True)
    assert isinstance(data, dict)
    assert data.get("dummy") is True
