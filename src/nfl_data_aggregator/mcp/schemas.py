"""Typed response contracts returned by the NFL data MCP tools."""

from typing import Any

from pydantic import BaseModel, Field


class RefreshMetadata(BaseModel):
    force_requested: bool = False
    refreshed: bool = False
    source: str | None = None
    records_written: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PlayerRecord(BaseModel):
    player_id: str
    espn_id: str | None = None
    nflverse_id: str | None = None
    name: str
    team: str | None = None
    position: str | None = None
    status: str | None = None
    height: str | None = None
    weight: int | None = None
    experience: int | None = None


class PlayerSearchResult(BaseModel):
    query: str
    players: list[PlayerRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class PerformanceRecord(BaseModel):
    game_id: str
    season: int | None = None
    week: int | None = None
    opponent: str | None = None
    home_away: str | None = None
    kickoff_time: str | None = None
    pass_completions: int | None = None
    pass_attempts: int | None = None
    pass_yards: int | None = None
    pass_tds: int | None = None
    interceptions: int | None = None
    passer_rating: float | None = None
    rush_attempts: int | None = None
    rush_yards: int | None = None
    rush_tds: int | None = None
    yards_per_carry: float | None = None
    receptions: int | None = None
    targets: int | None = None
    receiving_yards: int | None = None
    receiving_tds: int | None = None
    yards_per_reception: float | None = None
    fumbles: int | None = None
    fumbles_lost: int | None = None
    fantasy_points: float | None = None
    snaps: int | None = None
    snap_pct: float | None = None
    advanced_stats: dict[str, Any] | None = None
    source: str | None = None
    source_timestamp: str | None = None
    ingested_at: str | None = None


class PlayerPerformancesResult(BaseModel):
    player: PlayerRecord
    performances: list[PerformanceRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class GameRecord(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: str | None = None
    home_team: str
    away_team: str
    kickoff_time: str | None = None
    venue: str | None = None
    venue_location: dict[str, Any] | None = None
    weather_conditions: dict[str, Any] | None = None
    final_score: str | None = None


class GamesResult(BaseModel):
    games: list[GameRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class DefenseRecord(BaseModel):
    team: str
    season: int
    week_through: int
    pass_yards_allowed: float | None = None
    rush_yards_allowed: float | None = None
    points_allowed: float | None = None
    position_fantasy_points_allowed: dict[str, Any] | None = None
    pressure_rate: float | None = None
    coverage_grades: dict[str, Any] | None = None
    source: str | None = None
    updated_at: str | None = None


class GameContextResult(BaseModel):
    game: GameRecord
    home_defense: DefenseRecord | None = None
    away_defense: DefenseRecord | None = None
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class RosterResult(BaseModel):
    team: str
    include_all_positions: bool = False
    players: list[PlayerRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class HealthResult(BaseModel):
    status: str
    database: str
    detail: str | None = None


class CacheStatusResult(BaseModel):
    database: dict[str, str]
    record_counts: dict[str, int]
    cached_seasons: list[int] = Field(default_factory=list)
    cached_weeks: dict[str, list[int]] = Field(default_factory=dict)
    available_domains: dict[str, bool]
    newest_odds_snapshot: str | None = None
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class OddsEventRecord(BaseModel):
    event_id: str
    sport_key: str
    sport_title: str | None = None
    commence_time: str
    home_team: str
    away_team: str
    game_id: str | None = None
    discovered_at: str | None = None
    updated_at: str | None = None


class OddsEventsResult(BaseModel):
    sport_key: str
    events: list[OddsEventRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class OddsOutcomeRecord(BaseModel):
    name: str
    participant: str | None = None
    price: float
    point: float | None = None
    player_id: str | None = None
    extra_data: dict[str, Any] | None = None


class OddsMarketRecord(BaseModel):
    market_key: str
    last_update: str | None = None
    outcomes: list[OddsOutcomeRecord] = Field(default_factory=list)


class OddsBookmakerRecord(BaseModel):
    bookmaker_key: str
    bookmaker_title: str | None = None
    markets: list[OddsMarketRecord] = Field(default_factory=list)


class OddsQuotaRecord(BaseModel):
    remaining: int | None = None
    used: int | None = None
    last: int | None = None


class OddsSnapshotRecord(BaseModel):
    snapshot_id: int
    fetched_at: str
    requested_markets: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    requested_bookmakers: list[str] = Field(default_factory=list)
    odds_format: str = "american"
    outcome_count: int = 0
    quota: OddsQuotaRecord = Field(default_factory=OddsQuotaRecord)
    bookmakers: list[OddsBookmakerRecord] = Field(default_factory=list)


class OddsCacheMetadata(BaseModel):
    force_requested: bool = False
    refreshed: bool = False
    stale: bool = False
    ttl_seconds: int = 900
    age_seconds: float | None = None
    warnings: list[str] = Field(default_factory=list)


class BettingLinesResult(BaseModel):
    event: OddsEventRecord
    snapshot: OddsSnapshotRecord
    cache: OddsCacheMetadata = Field(default_factory=OddsCacheMetadata)


class BettingLineHistoryResult(BaseModel):
    event: OddsEventRecord
    snapshots: list[OddsSnapshotRecord] = Field(default_factory=list)
