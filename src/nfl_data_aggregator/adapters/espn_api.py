from typing import Any, Dict, Optional
import json
import logging
import time
from pathlib import Path
from urllib.parse import urljoin
import os

logger = logging.getLogger(__name__)

# Default cache directory relative to package
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "espn"


class ESPNClient:
    """Core ESPN HTTP client.

    - Checks for local JSON data under data/espn/{sport}/{league}/ before making
      network requests unless `force=True` is passed to `get`.
    - Adds a polite delay between requests (rate_limit_delay seconds).
    - Uses a requests.Session for connection reuse when available.

    Usage:
        client = ESPNClient(base_url="https://site.api.espn.com", rate_limit_delay=1.0)
        data = client.get('/apis/site/v2/sports/football/nfl/scoreboard', params={...}, sport='football', league='nfl')
    """

    def __init__(
        self,
        base_url: str = "https://site.api.espn.com",
        data_dir: Optional[Path] = None,
        rate_limit_delay: float = 0.75,
        default_timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        # Cache TTL (seconds) - default to 7 days, configurable via env
        self.cache_ttl_seconds = int(os.environ.get("NFL_DATA_CACHE_TTL_SECONDS", 7 * 24 * 3600))
        self.rate_limit_delay = float(rate_limit_delay)
        self.default_timeout = float(default_timeout)
        self._last_request_time: Optional[float] = None

        try:
            import requests

            self._requests = requests
            self._session = requests.Session()
            # ESPN's edge may return 403 for explicit User-Agent headers. Keep
            # the JSON preference, but remove requests' default User-Agent.
            self._session.headers.update({"Accept": "application/json"})
            self._session.headers.pop("User-Agent", None)
            # flag indicating whether the last GET was served from network
            self._last_response_from_network = False
        except Exception:  # pragma: no cover - requests not installed in some environments
            self._requests = None
            self._session = None
            logger.debug("requests not available; network calls will be disabled")

    # Cache index helpers
    def _cache_index_path(self) -> Path:
        idx_dir = self.data_dir / (self.sport or "") / (self.league or "")
        idx_dir.mkdir(parents=True, exist_ok=True)
        return idx_dir / "cache_index.json"

    def _load_cache_index(self) -> Dict[str, Any]:
        p = self._cache_index_path()
        if not p.exists():
            return {}
        try:
            with p.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            logger.exception("Failed to load cache index %s", p)
            return {}

    def _save_cache_index(self, index: Dict[str, Any]) -> None:
        p = self._cache_index_path()
        try:
            with p.open("w", encoding="utf-8") as fh:
                json.dump(index, fh, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to write cache index %s", p)

    def _update_cache_index_entry(self, key: str, meta: Dict[str, Any]) -> None:
        """Add or update an index entry. meta should include at least 'path' and 'type'."""
        idx = self._load_cache_index()
        meta = dict(meta)
        meta["timestamp"] = int(time.time())
        idx[key] = meta
        self._save_cache_index(idx)

    def _remove_cache_index_entry(self, key: str) -> None:
        idx = self._load_cache_index()
        if key in idx:
            try:
                # attempt to remove file on disk if exists
                p = Path(idx[key].get("path"))
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        logger.exception("Failed to remove cached file %s", p)
            finally:
                idx.pop(key, None)
                self._save_cache_index(idx)

    def _is_cache_fresh(self, key: str, ttl_seconds: Optional[int] = None) -> bool:
        ttl = int(ttl_seconds) if ttl_seconds is not None else int(self.cache_ttl_seconds)
        idx = self._load_cache_index()
        ent = idx.get(key)
        if not ent:
            return False
        ts = ent.get("timestamp")
        if not ts:
            return False
        return (int(time.time()) - int(ts)) <= ttl

    def clear_cache(self, *, team_id: Optional[str] = None, athlete_id: Optional[str] = None, older_than_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Purge cached entries. Returns a dict of removed keys -> True.

        - If team_id specified, removes depthchart entries for that team.
        - If athlete_id specified, removes athlete cache entries for that athlete.
        - If older_than_seconds specified, removes entries older than that value.
        If nothing specified all entries older than the default TTL are removed.
        """
        idx = self._load_cache_index()
        removed = {}
        now = int(time.time())
        keys = list(idx.keys())
        for k in keys:
            ent = idx.get(k, {})
            typ = ent.get("type")
            path = ent.get("path")
            ts = ent.get("timestamp") or 0
            age = now - int(ts)
            should_remove = False
            if team_id and typ == "depthchart" and str(ent.get("team_id")) == str(team_id):
                should_remove = True
            if athlete_id and typ == "athlete" and str(ent.get("athlete_id")) == str(athlete_id):
                should_remove = True
            if older_than_seconds is not None and age > int(older_than_seconds):
                should_remove = True
            # default behavior: if none of team_id/athlete_id/older_than_seconds specified, remove entries older than TTL
            if team_id is None and athlete_id is None and older_than_seconds is None:
                if age > int(self.cache_ttl_seconds):
                    should_remove = True

            if should_remove:
                try:
                    if path:
                        p = Path(path)
                        if p.exists():
                            p.unlink()
                except Exception:
                    logger.exception("Failed to remove cache file %s", path)
                idx.pop(k, None)
                removed[k] = True

        self._save_cache_index(idx)
        return removed

    def _sleep_if_needed(self) -> None:
        if self._last_request_time is None:
            self._last_request_time = time.time()
            return
        elapsed = time.time() - self._last_request_time
        remaining = self.rate_limit_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_time = time.time()

    def _find_local_data(self, sport: Optional[str], league: Optional[str], path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Path]:
        """Heuristic search for a local JSON file corresponding to the requested resource.

        Strategy:
        - If data/espn/{sport}/{league}/{last_segment}.json exists, return it.
        - Otherwise search for any JSON file in the directory that contains the last segment.
        - Returns None if no candidate found.
        """
        if not sport or not league:
            return None
        base = self.data_dir / sport / league
        if not base.exists() or not base.is_dir():
            return None

        last = Path(path).name or path.replace("/", "_")
        direct = base / f"{last}.json"
        if direct.exists():
            return direct

        for f in base.glob("*.json"):
            if last in f.stem:
                return f

        return None

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, *, sport: Optional[str] = None, league: Optional[str] = None, force: bool = False, timeout: Optional[float] = None) -> Any:
        """GET JSON from ESPN API or from local cache.

        - path: path relative to the base_url (may start with '/').
        - params: optional query params dict.
        - sport/league: used to check local cache under data/espn/{sport}/{league}/.
        - force: if True, always call network even if local data exists.
        - timeout: per-request timeout in seconds.

        Default query params added automatically (unless overridden by caller):
        - lang: 'en'
        - region: 'us'
        """
        # Merge default ESPN query params with caller-provided params; caller wins on key conflict
        default_query_params = {"lang": "en", "region": "us"}
        merged_params: Dict[str, Any] = {**default_query_params, **(params or {})}

        # Try local data first unless force=True
        if not force:
            local = self._find_local_data(sport, league, path, merged_params)
            if local:
                try:
                    with local.open("r", encoding="utf-8") as fh:
                        self._last_response_from_network = False
                        return json.load(fh)
                except Exception as exc:  # fall back to network call on parse errors
                    logger.exception("Failed to read local ESPN data %s: %s", local, exc)

        if self._requests is None or self._session is None:
            raise RuntimeError("requests library is required for network access; no local data found or force=True")

        url = urljoin(self.base_url, path.lstrip("/"))

        # rate-limit politely
        self._sleep_if_needed()

        try:
            resp = self._session.get(url, params=merged_params, timeout=timeout or self.default_timeout)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            # mark that the most recent successful response was from the network
            self._last_response_from_network = True
            if "application/json" in content_type or resp.text.strip().startswith("{") or resp.text.strip().startswith("["):
                return resp.json()
            # fallback: try to parse as json anyway
            try:
                return resp.json()
            except Exception:
                logger.warning("ESPN response for %s was not JSON; returning text", url)
                return resp.text
        except Exception as exc:
            logger.exception("Error calling ESPN API %s: %s", url, exc)
            raise


class NFLClient(ESPNClient):
    """ESPN client preconfigured for NFL-specific endpoints.

    Provides small convenience methods for common NFL endpoints described in
    `ESPN_API.md`. Methods accept a `force` flag to bypass local cache.
    """

    def __init__(self, *args, site_base: str = "https://site.api.espn.com", core_base: str = "https://sports.core.api.espn.com", cdn_base: str = "https://cdn.espn.com", **kwargs):
        # default base is the site API; individual methods may call the core or cdn bases
        super().__init__(base_url=site_base, *args, **kwargs)
        self.core_base = core_base.rstrip("/") + "/"
        self.cdn_base = cdn_base.rstrip("/") + "/"
        self.sport = "football"
        self.league = "nfl"

    def scoreboard(self, dates: Optional[str] = None, week: Optional[int] = None, seasontype: Optional[int] = None, force: bool = False) -> Any:
        path = "/apis/site/v2/sports/football/nfl/scoreboard"
        params: Dict[str, Any] = {}
        if dates:
            params["dates"] = dates
        if week is not None:
            params["week"] = week
        if seasontype is not None:
            params["seasontype"] = seasontype
        return self.get(path, params=params, sport=self.sport, league=self.league, force=force)

    def teams(self, force: bool = False) -> Any:
        path = "/apis/site/v2/sports/football/nfl/teams"
        return self.get(path, sport=self.sport, league=self.league, force=force)

    def team(self, team_id: str, force: bool = False) -> Any:
        path = f"/apis/site/v2/sports/football/nfl/teams/{team_id}"
        return self.get(path, sport=self.sport, league=self.league, force=force)

    def roster(self, team_id: str, force: bool = False) -> Any:
        path = f"/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
        return self.get(path, sport=self.sport, league=self.league, force=force)

    def player_gamelog(self, athlete_id: str, season: int, force: bool = False) -> Any:
        """Fetch a player's game log for a given season."""
        path = f"/apis/common/v3/sports/football/nfl/athletes/{athlete_id}/gamelog"
        params = {"season": season}
        return self.get(path, params=params, sport=self.sport, league=self.league, force=force)

    def schedule(self, team_id: Optional[str] = None, year: Optional[int] = None, week: Optional[int] = None, force: bool = False) -> Any:
        if team_id:
            path = f"/apis/site/v2/sports/football/nfl/teams/{team_id}/schedule"
            params = {}
            if year:
                params["season"] = year
            return self.get(path, params=params, sport=self.sport, league=self.league, force=force)
        path = "/core/nfl/schedule"
        params = {}
        if year:
            params["year"] = year
        if week is not None:
            params["week"] = week
        # use CDN endpoint for schedule if local cache absent
        return self._get_with_base(self.cdn_base, path, params=params, force=force)

    def standings(self, season: Optional[int] = None, force: bool = False) -> Any:
        path = "/apis/site/v2/sports/football/nfl/standings"
        params = {}
        if season:
            params["season"] = season
        return self.get(path, params=params, sport=self.sport, league=self.league, force=force)

    def events(self, dates: Optional[str] = None, limit: Optional[int] = None, force: bool = False) -> Any:
        path = "/v2/sports/football/leagues/nfl/events"
        params: Dict[str, Any] = {}
        if dates:
            params["dates"] = dates
        if limit is not None:
            params["limit"] = limit
        return self._get_with_core(path, params=params, force=force)

    def event_summary(self, event_id: str, force: bool = False) -> Any:
        path = "/apis/site/v2/sports/football/nfl/summary"
        params = {"event": event_id}
        return self.get(path, params=params, sport=self.sport, league=self.league, force=force)

    def boxscore(self, game_id: str, force: bool = False) -> Any:
        # CDN boxscore
        path = "/core/nfl/boxscore"
        params = {"xhr": 1, "gameId": game_id}
        return self._get_with_base(self.cdn_base, path, params=params, force=force)

    def plays(self, event_id: str, limit: Optional[int] = None, force: bool = False) -> Any:
        # core plays endpoint
        path = f"/v2/sports/football/leagues/nfl/events/{event_id}/competitions/{event_id}/plays"
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        return self._get_with_core(path, params=params, force=force)

    def depth_chart(self, team_id: str, year: str, limit: Optional[int] = None, force: bool = False) -> Any:
        path = f"/v2/sports/football/leagues/nfl/seasons/{year}/teams/{team_id}/depthcharts"
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        # Attempt to get data (may come from local cache or network). If network
        # returns data successfully we will persist it to the local data dir so
        # subsequent calls can use the cached file.
        data = self._get_with_core(path, params=params, force=force)

        # If we obtained a dict/list-like response from the network, attempt to write it to disk
        cache_path = None
        try:
            if data is not None and getattr(self, "_last_response_from_network", False):
                out_dir = self.data_dir / "football" / "nfl" / "depthcharts"
                out_dir.mkdir(parents=True, exist_ok=True)
                cache_path = out_dir / f"{team_id}-{year}.json"
                try:
                    import json as _json

                    with cache_path.open("w", encoding="utf-8") as fh:
                        _json.dump(data, fh, ensure_ascii=False, indent=2)
                except Exception:
                    logger.exception("Failed to write depthchart cache %s", cache_path)
        except Exception:
            logger.exception("Unexpected error while caching depth chart for %s %s", team_id, year)

        # Update cache index if we wrote a cache file
        try:
            if cache_path is not None and cache_path.exists():
                self._update_cache_index_entry(f"depthchart-{team_id}-{year}", {"path": str(cache_path), "type": "depthchart", "team_id": team_id})
        except Exception:
            logger.exception("Failed to update cache index for depth chart %s %s", team_id, year)

        return data

    def _get_with_core(self, path: str, params: Optional[Dict[str, Any]] = None, force: bool = False) -> Any:
        return self._get_with_base(self.core_base, path, params=params, force=force)

    def _get_with_base(self, base: str, path: str, params: Optional[Dict[str, Any]] = None, force: bool = False) -> Any:
        # Temporarily use a different base URL for this call but still honour local data lookup
        original_base = self.base_url
        try:
            self.base_url = base.rstrip("/") + "/"
            return self.get(path, params=params, sport=self.sport, league=self.league, force=force)
        finally:
            self.base_url = original_base

    # Helper methods to resolve team names -> ESPN team ids using local team list
    def _load_all_teams(self) -> Any:
        """Load the local `all-teams.json` file if present under data/espn/football/nfl."""
        teams_path = self.data_dir / "football" / "nfl" / "all-teams.json"
        if not teams_path.exists():
            return None
        try:
            with teams_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def find_team_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a team entry by matching common name fields (case-insensitive).

        Matches against 'displayName', 'shortDisplayName', 'name', 'abbreviation', and 'slug'.
        Returns the team object (as found in the all-teams.json) or None.
        """
        data = self._load_all_teams()
        if not data:
            return None
        # navigate structure
        leagues = data.get("sports", [])
        fields = ("displayName", "shortDisplayName", "name", "abbreviation", "slug", "nickname", "location")
        # Exact match priority
        for sport in leagues:
            for league in sport.get("leagues", []) if sport.get("leagues") else []:
                for t in league.get("teams", []):
                    team = t.get("team") or {}
                    for key in fields:
                        val = team.get(key)
                        if val and val.lower() == name.lower():
                            return team

        # Tokenized partial match: split input into tokens and check if any token appears in a team field
        tokens = [tok for tok in name.lower().split() if tok]
        if tokens:
            for sport in leagues:
                for league in sport.get("leagues", []) if sport.get("leagues") else []:
                    for t in league.get("teams", []):
                        team = t.get("team") or {}
                        for key in fields:
                            val = team.get(key)
                            if val:
                                low = val.lower()
                                if any(tok in low for tok in tokens):
                                    return team
        return None

    def find_team_id(self, name: str) -> Optional[str]:
        team = self.find_team_by_name(name)
        return team.get("id") if team else None

    def depth_chart_for_team_name(self, team_name: str, year: Optional[int] = None, limit: Optional[int] = None, force: bool = False) -> Any:
        """Convenience wrapper that resolves a team name to an ESPN team id and returns the depth chart.

        If `year` is None the caller should substitute the current season externally.
        """
        team_id = self.find_team_id(team_name)
        if not team_id:
            raise ValueError(f"Could not resolve team name to an ESPN team id: {team_name}")
        if year is None:
            raise ValueError("year is required for depth_chart_for_team_name; supply current year before calling")
        return self.depth_chart(team_id=team_id, year=str(year), limit=limit, force=force)

    def fetch_by_ref(self, ref_url: str, force: bool = False) -> Any:
        """Fetch a resource by its absolute reference URL.

        Attempts to use the configured requests session. If network access is not
        unavailable, attempts to fall back to a local file heuristic (noting
        that not all refs will have local cached files). If neither is
        available, returns a minimal dict containing the id parsed from the
        URL so callers can still proceed in degraded mode.
        """
        # If a session is available use it (network); on success save to disk.
        if getattr(self, "_session", None) is not None:
            try:
                resp = self._session.get(ref_url, timeout=self.default_timeout)
                resp.raise_for_status()
                # try JSON
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"_raw_text": resp.text}

                # attempt to parse athlete id and season from the ref URL for naming
                try:
                    import re, json as _json

                    m = re.search(r"/seasons/(\d{4})/athletes/(\d+)", ref_url)
                    if m:
                        season = m.group(1)
                        aid = m.group(2)
                        out_dir = self.data_dir / "football" / "nfl" / "athletes"
                        out_dir.mkdir(parents=True, exist_ok=True)
                        cache_path = out_dir / f"{aid}-{season}.json"
                        try:
                            with cache_path.open("w", encoding="utf-8") as fh:
                                _json.dump(payload, fh, ensure_ascii=False, indent=2)
                        except Exception:
                            logger.exception("Failed to write athlete cache %s", cache_path)
                    else:
                        # fallback: try to capture trailing numeric id
                        m2 = re.search(r"(\d{3,})", ref_url)
                        if m2:
                            aid = m2.group(1)
                            out_dir = self.data_dir / "football" / "nfl" / "athletes"
                            out_dir.mkdir(parents=True, exist_ok=True)
                            cache_path = out_dir / f"{aid}.json"
                            try:
                                with cache_path.open("w", encoding="utf-8") as fh:
                                    _json.dump(payload, fh, ensure_ascii=False, indent=2)
                            except Exception:
                                logger.exception("Failed to write athlete cache %s", cache_path)
                except Exception:
                    logger.exception("Failed to cache athlete response for ref %s", ref_url)

                # Update cache index
                try:
                    if "id" in payload and 'cache_path' in locals() and cache_path is not None and cache_path.exists():
                        self._update_cache_index_entry(f"athlete-{payload['id']}", {"path": str(cache_path), "type": "athlete", "athlete_id": payload["id"]})
                except Exception:
                    logger.exception("Failed to update cache index for athlete ref %s", ref_url)

                return payload
            except Exception:
                logger.exception("Failed to fetch resource by ref %s", ref_url)

        # Local fallback: try to find a JSON file with the last path component
        try:
            last = ref_url.rstrip("/").split("/")[-1]
            # last might be an id with query params; strip them
            if "?" in last:
                last = last.split("?")[0]
            # search the local data dir for a matching file
            for f in (self.data_dir / "football" / "nfl").rglob("*.json"):
                if last in f.stem:
                    try:
                        with f.open("r", encoding="utf-8") as fh:
                            return json.load(fh)
                    except Exception:
                        continue
        except Exception:
            pass

        # Best-effort id extraction
        try:
            import re

            m = re.search(r"athletes?/(\d+)", ref_url)
            if m:
                return {"id": m.group(1)}
        except Exception:
            pass

        # Last resort: return the raw URL
        return {"ref": ref_url}
