"""Database-first Odds API queries, refreshes, and immutable snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.espn_api import NFLClient
from ..adapters.odds_api import (
    OddsAPIClient,
    OddsAPIError,
    default_markets,
    normalize_values,
)
from ..config.config import settings
from ..db.repository import OddsRepo
from ..db.sa_models import Game, OddsEvent, OddsLine, OddsSnapshot, Player
from ..mcp.schemas import (
    BettingLineHistoryResult,
    BettingLinesResult,
    OddsBookmakerRecord,
    OddsCacheMetadata,
    OddsEventRecord,
    OddsEventsResult,
    OddsMarketRecord,
    OddsOutcomeRecord,
    OddsQuotaRecord,
    OddsSnapshotRecord,
    RefreshMetadata,
)


class OddsQueryError(ValueError):
    """A concise, user-facing odds query or refresh failure."""


class OddsQueryService:
    def __init__(
        self,
        session: Session,
        client: OddsAPIClient | None = None,
        *,
        espn_client: NFLClient | None = None,
        now=None,
    ):
        self.session = session
        self.client = client or OddsAPIClient()
        self.espn_client = espn_client or NFLClient()
        self.repo = OddsRepo(session)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ttl_seconds = max(0, int(settings.ODDS_CACHE_TTL_SECONDS))

    def list_events(
        self,
        sport_key: str = "americanfootball_nfl",
        *,
        commence_time_from: str | None = None,
        commence_time_to: str | None = None,
        limit: int = 100,
        force: bool = False,
    ) -> OddsEventsResult:
        limit = _validate_limit(limit)
        start = _parse_optional_datetime(commence_time_from, "commence_time_from")
        end = _parse_optional_datetime(commence_time_to, "commence_time_to")
        if start and end and start > end:
            raise OddsQueryError("commence_time_from must not be after commence_time_to")

        cached = self.repo.list_events(
            sport_key, commence_from=start, commence_to=end, limit=limit
        )
        newest_update = max((_as_utc(event.updated_at) for event in cached), default=None)
        stale = newest_update is None or self._age_seconds(newest_update) >= self.ttl_seconds
        refresh = RefreshMetadata(force_requested=force)

        if force or stale:
            try:
                response = self.client.list_events(
                    sport_key,
                    commence_time_from=_iso_z(start),
                    commence_time_to=_iso_z(end),
                )
                written = self._persist_events(sport_key, response.data)
                self.session.commit()
                refresh = RefreshMetadata(
                    force_requested=force,
                    refreshed=True,
                    source="the-odds-api",
                    records_written={"odds_events": written},
                )
            except Exception as exc:
                self.session.rollback()
                if force or not cached:
                    raise OddsQueryError(f"Odds event refresh failed: {exc}") from exc
                refresh.warnings.append(f"Odds event refresh failed; returning cached events: {exc}")

        events = self.repo.list_events(
            sport_key, commence_from=start, commence_to=end, limit=limit
        )
        return OddsEventsResult(
            sport_key=sport_key,
            events=[_event_record(event) for event in events],
            refresh=refresh,
        )

    def get_betting_lines(
        self,
        sport_key: str,
        event_id: str,
        *,
        market_keys: list[str] | None = None,
        regions: list[str] | None = None,
        bookmakers: list[str] | None = None,
        force: bool = False,
    ) -> BettingLinesResult:
        markets = normalize_values(market_keys) or default_markets(sport_key)
        region_values = normalize_values(regions)
        bookmaker_values = normalize_values(bookmakers)
        if region_values and bookmaker_values:
            raise OddsQueryError("regions and bookmakers are mutually exclusive")
        if not bookmaker_values and not region_values:
            region_values = normalize_values(settings.ODDS_API_REGIONS)
        if not markets:
            raise OddsQueryError("at least one market key is required")

        event = self._ensure_event(sport_key, event_id)
        signature = _request_signature(markets, region_values, bookmaker_values)
        snapshot = self.repo.latest_snapshot(event_id, signature)
        age = self._age_seconds(snapshot.fetched_at) if snapshot else None
        stale = snapshot is None or age >= self.ttl_seconds
        warnings: list[str] = []
        refreshed = False

        if force or stale:
            try:
                response = self.client.get_event_odds(
                    sport_key,
                    event_id,
                    markets=markets,
                    regions=region_values or None,
                    bookmakers=bookmaker_values or None,
                )
                snapshot = self._persist_snapshot(
                    sport_key,
                    event_id,
                    response.data,
                    response.quota,
                    signature,
                    markets,
                    region_values,
                    bookmaker_values,
                )
                self.session.commit()
                refreshed = True
                age = 0.0
                stale = False
                event = self.repo.get_event(event_id) or event
            except Exception as exc:
                self.session.rollback()
                snapshot = self.repo.latest_snapshot(event_id, signature)
                if force or snapshot is None:
                    raise OddsQueryError(f"Odds refresh failed: {exc}") from exc
                age = self._age_seconds(snapshot.fetched_at)
                stale = True
                warnings.append(f"Odds refresh failed; returning stale snapshot: {exc}")

        if snapshot is None:
            raise OddsQueryError(f"No betting lines are stored for event {event_id}")
        return BettingLinesResult(
            event=_event_record(event),
            snapshot=_snapshot_record(snapshot),
            cache=OddsCacheMetadata(
                force_requested=force,
                refreshed=refreshed,
                stale=stale,
                ttl_seconds=self.ttl_seconds,
                age_seconds=age,
                warnings=warnings,
            ),
        )

    def get_betting_line_history(
        self,
        sport_key: str,
        event_id: str,
        *,
        market_keys: list[str] | None = None,
        bookmaker_keys: list[str] | None = None,
        participant: str | None = None,
        fetched_from: str | None = None,
        fetched_to: str | None = None,
        snapshot_limit: int = 20,
    ) -> BettingLineHistoryResult:
        snapshot_limit = _validate_limit(snapshot_limit)
        event = self.repo.get_event(event_id)
        if event is None or event.sport_key != sport_key:
            raise OddsQueryError(f"Odds event {event_id} not found for sport {sport_key}")
        start = _parse_optional_datetime(fetched_from, "fetched_from")
        end = _parse_optional_datetime(fetched_to, "fetched_to")
        if start and end and start > end:
            raise OddsQueryError("fetched_from must not be after fetched_to")

        markets = normalize_values(market_keys)
        books = normalize_values(bookmaker_keys)
        stmt = select(OddsSnapshot).where(OddsSnapshot.event_id == event_id)
        if start:
            stmt = stmt.where(OddsSnapshot.fetched_at >= start)
        if end:
            stmt = stmt.where(OddsSnapshot.fetched_at <= end)
        line_conditions = []
        if markets:
            line_conditions.append(OddsLine.market_key.in_(markets))
        if books:
            line_conditions.append(OddsLine.bookmaker_key.in_(books))
        if participant:
            line_conditions.append(OddsLine.participant.ilike(f"%{participant.strip()}%"))
        if line_conditions:
            stmt = stmt.join(OddsLine).where(*line_conditions).distinct()
        stmt = stmt.order_by(OddsSnapshot.fetched_at.desc(), OddsSnapshot.id.desc()).limit(
            snapshot_limit
        )
        snapshots = list(self.session.scalars(stmt).unique().all())
        return BettingLineHistoryResult(
            event=_event_record(event),
            snapshots=[
                _snapshot_record(
                    snapshot,
                    market_keys=markets,
                    bookmaker_keys=books,
                    participant=participant,
                )
                for snapshot in snapshots
            ],
        )

    def _ensure_event(self, sport_key: str, event_id: str) -> OddsEvent:
        event = self.repo.get_event(event_id)
        if event is not None:
            if event.sport_key != sport_key:
                raise OddsQueryError(
                    f"Odds event {event_id} belongs to {event.sport_key}, not {sport_key}"
                )
            return event
        try:
            response = self.client.list_events(sport_key, event_ids=[event_id])
            written = self._persist_events(sport_key, response.data)
            event = self.repo.get_event(event_id)
            if written == 0 or event is None:
                raise OddsQueryError(f"Odds event {event_id} was not found")
            self.session.commit()
            return event
        except OddsQueryError:
            self.session.rollback()
            raise
        except Exception as exc:
            self.session.rollback()
            raise OddsQueryError(f"Odds event lookup failed: {exc}") from exc

    def _persist_events(self, sport_key: str, payload: Any) -> int:
        if not isinstance(payload, list):
            raise OddsAPIError("The Odds API events response must be a list")
        written = 0
        for item in payload:
            if not isinstance(item, dict):
                raise OddsAPIError("The Odds API returned a malformed event")
            event_id = str(item.get("id") or "").strip()
            commence = _parse_datetime(item.get("commence_time"), "commence_time")
            home = str(item.get("home_team") or "").strip()
            away = str(item.get("away_team") or "").strip()
            if not event_id or not home or not away:
                raise OddsAPIError("The Odds API returned an incomplete event")
            existing = self.repo.get_event(event_id)
            game_id = existing.game_id if existing else None
            if game_id is None:
                game_id = self._match_local_game(sport_key, home, away, commence)
            self.repo.upsert_event(
                event_id,
                sport_key=str(item.get("sport_key") or sport_key),
                sport_title=item.get("sport_title"),
                commence_time=commence,
                home_team=home,
                away_team=away,
                game_id=game_id,
            )
            written += 1
        self.session.flush()
        return written

    def _persist_snapshot(
        self,
        sport_key: str,
        event_id: str,
        payload: Any,
        quota: dict[str, int | None],
        signature: str,
        markets: list[str],
        regions: list[str],
        bookmakers: list[str],
    ) -> OddsSnapshot:
        if not isinstance(payload, dict):
            raise OddsAPIError("The Odds API event odds response must be an object")
        if str(payload.get("id") or "") != event_id:
            raise OddsAPIError("The Odds API event odds response has an unexpected event id")
        self._persist_events(sport_key, [payload])
        snapshot = self.repo.add_snapshot(
            event_id=event_id,
            fetched_at=self.now(),
            request_signature=signature,
            requested_markets=markets,
            regions=regions or None,
            bookmakers=bookmakers or None,
            odds_format="american",
            outcome_count=0,
            requests_remaining=quota.get("remaining"),
            requests_used=quota.get("used"),
            requests_last=quota.get("last"),
        )
        self.session.flush()

        player_map = self._unique_player_map()
        count = 0
        bookmaker_payload = payload.get("bookmakers", [])
        if not isinstance(bookmaker_payload, list):
            raise OddsAPIError("The Odds API returned malformed bookmakers")
        for bookmaker in bookmaker_payload:
            if not isinstance(bookmaker, dict) or not bookmaker.get("key"):
                raise OddsAPIError("The Odds API returned a malformed bookmaker")
            market_payload = bookmaker.get("markets", [])
            if not isinstance(market_payload, list):
                raise OddsAPIError("The Odds API returned malformed markets")
            for market in market_payload:
                if not isinstance(market, dict) or not market.get("key"):
                    raise OddsAPIError("The Odds API returned a malformed market")
                market_key = str(market["key"])
                updated = _parse_optional_datetime(market.get("last_update"), "last_update")
                outcomes = market.get("outcomes", [])
                if not isinstance(outcomes, list):
                    raise OddsAPIError("The Odds API returned malformed outcomes")
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        raise OddsAPIError("The Odds API returned a malformed outcome")
                    name = str(outcome.get("name") or "").strip()
                    if not name or outcome.get("price") is None:
                        raise OddsAPIError("The Odds API returned an incomplete outcome")
                    try:
                        price = float(outcome["price"])
                        point = float(outcome["point"]) if outcome.get("point") is not None else None
                    except (TypeError, ValueError) as exc:
                        raise OddsAPIError("The Odds API returned non-numeric odds") from exc
                    participant = outcome.get("description")
                    participant = str(participant).strip() if participant is not None else None
                    player_id = None
                    if participant and market_key.startswith("player_"):
                        player_id = player_map.get(_normalize_name(participant))
                    extra = {
                        key: value
                        for key, value in outcome.items()
                        if key not in {"name", "description", "price", "point"}
                    }
                    self.repo.add_line(
                        snapshot_id=snapshot.id,
                        bookmaker_key=str(bookmaker["key"]),
                        bookmaker_title=bookmaker.get("title"),
                        market_key=market_key,
                        market_last_update=updated,
                        outcome_name=name,
                        participant=participant,
                        price=price,
                        point=point,
                        player_id=player_id,
                        extra_data=extra or None,
                    )
                    count += 1
        snapshot.outcome_count = count
        self.session.flush()
        return snapshot

    def _unique_player_map(self) -> dict[str, str]:
        players = list(self.session.scalars(select(Player)).all())
        grouped: dict[str, list[str]] = {}
        for player in players:
            grouped.setdefault(_normalize_name(player.name), []).append(player.player_id)
        return {name: ids[0] for name, ids in grouped.items() if name and len(ids) == 1}

    def _match_local_game(
        self, sport_key: str, home_name: str, away_name: str, commence: datetime
    ) -> str | None:
        if sport_key != "americanfootball_nfl":
            return None
        home = self.espn_client.find_team_by_name(home_name)
        away = self.espn_client.find_team_by_name(away_name)
        if not home or not away:
            return None
        home_abbr = str(home.get("abbreviation") or "").upper()
        away_abbr = str(away.get("abbreviation") or "").upper()
        candidates = list(
            self.session.scalars(
                select(Game).where(
                    Game.home_team == home_abbr,
                    Game.away_team == away_abbr,
                    Game.kickoff_time.is_not(None),
                )
            ).all()
        )
        matches = [
            game
            for game in candidates
            if abs((_as_utc(game.kickoff_time) - commence).total_seconds()) <= 12 * 3600
        ]
        if len(matches) != 1:
            return None
        game_id = matches[0].game_id
        already_linked = self.session.scalar(
            select(OddsEvent.event_id).where(OddsEvent.game_id == game_id).limit(1)
        )
        return game_id if already_linked is None else None

    def _age_seconds(self, value: datetime) -> float:
        return max(0.0, (self.now() - _as_utc(value)).total_seconds())


def _request_signature(markets: list[str], regions: list[str], bookmakers: list[str]) -> str:
    canonical = json.dumps(
        {
            "markets": sorted(markets),
            "regions": sorted(regions),
            "bookmakers": sorted(bookmakers),
            "odds_format": "american",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_record(event: OddsEvent) -> OddsEventRecord:
    return OddsEventRecord(
        event_id=event.event_id,
        sport_key=event.sport_key,
        sport_title=event.sport_title,
        commence_time=_as_utc(event.commence_time).isoformat(),
        home_team=event.home_team,
        away_team=event.away_team,
        game_id=event.game_id,
        discovered_at=_as_utc(event.discovered_at).isoformat() if event.discovered_at else None,
        updated_at=_as_utc(event.updated_at).isoformat() if event.updated_at else None,
    )


def _snapshot_record(
    snapshot: OddsSnapshot,
    *,
    market_keys: list[str] | None = None,
    bookmaker_keys: list[str] | None = None,
    participant: str | None = None,
) -> OddsSnapshotRecord:
    markets_filter = set(market_keys or [])
    books_filter = set(bookmaker_keys or [])
    participant_filter = participant.strip().casefold() if participant else None
    grouped: dict[tuple[str, str | None], dict[tuple[str, str | None], list[OddsLine]]] = {}
    for line in snapshot.lines:
        if markets_filter and line.market_key not in markets_filter:
            continue
        if books_filter and line.bookmaker_key not in books_filter:
            continue
        if participant_filter and participant_filter not in (line.participant or "").casefold():
            continue
        book_key = (line.bookmaker_key, line.bookmaker_title)
        market_key = (
            line.market_key,
            _as_utc(line.market_last_update).isoformat() if line.market_last_update else None,
        )
        grouped.setdefault(book_key, {}).setdefault(market_key, []).append(line)

    books = []
    for (book_key, title), markets in sorted(grouped.items()):
        market_records = []
        for (market_key, last_update), lines in sorted(markets.items()):
            market_records.append(
                OddsMarketRecord(
                    market_key=market_key,
                    last_update=last_update,
                    outcomes=[
                        OddsOutcomeRecord(
                            name=line.outcome_name,
                            participant=line.participant,
                            price=line.price,
                            point=line.point,
                            player_id=line.player_id,
                            extra_data=line.extra_data,
                        )
                        for line in sorted(
                            lines,
                            key=lambda row: (
                                row.participant or "",
                                row.outcome_name,
                                row.point if row.point is not None else float("-inf"),
                            ),
                        )
                    ],
                )
            )
        books.append(
            OddsBookmakerRecord(
                bookmaker_key=book_key,
                bookmaker_title=title,
                markets=market_records,
            )
        )
    return OddsSnapshotRecord(
        snapshot_id=snapshot.id,
        fetched_at=_as_utc(snapshot.fetched_at).isoformat(),
        requested_markets=list(snapshot.requested_markets or []),
        regions=list(snapshot.regions or []),
        requested_bookmakers=list(snapshot.bookmakers or []),
        odds_format=snapshot.odds_format,
        outcome_count=snapshot.outcome_count,
        quota=OddsQuotaRecord(
            remaining=snapshot.requests_remaining,
            used=snapshot.requests_used,
            last=snapshot.requests_last,
        ),
        bookmakers=books,
    )


def _parse_optional_datetime(value: Any, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    return _parse_datetime(value, field)


def _parse_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str):
        raise OddsQueryError(f"{field} must be an ISO 8601 timestamp")
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise OddsQueryError(f"{field} must be an ISO 8601 timestamp") from exc


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_z(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise OddsQueryError("limit must be between 1 and 100")
    return limit
