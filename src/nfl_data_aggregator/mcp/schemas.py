"""Typed response contracts returned by the NFL data MCP tools."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class RefreshMetadata(BaseModel):
    force_requested: bool = False
    refreshed: bool = False
    source: Optional[str] = None
    records_written: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PlayerRecord(BaseModel):
    player_id: str
    espn_id: Optional[str] = None
    nflverse_id: Optional[str] = None
    name: str
    team: Optional[str] = None
    position: Optional[str] = None
    status: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[int] = None
    experience: Optional[int] = None


class PlayerSearchResult(BaseModel):
    query: str
    players: list[PlayerRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class PerformanceRecord(BaseModel):
    game_id: str
    season: Optional[int] = None
    week: Optional[int] = None
    opponent: Optional[str] = None
    home_away: Optional[str] = None
    kickoff_time: Optional[str] = None
    pass_completions: Optional[int] = None
    pass_attempts: Optional[int] = None
    pass_yards: Optional[int] = None
    pass_tds: Optional[int] = None
    interceptions: Optional[int] = None
    passer_rating: Optional[float] = None
    rush_attempts: Optional[int] = None
    rush_yards: Optional[int] = None
    rush_tds: Optional[int] = None
    yards_per_carry: Optional[float] = None
    receptions: Optional[int] = None
    targets: Optional[int] = None
    receiving_yards: Optional[int] = None
    receiving_tds: Optional[int] = None
    yards_per_reception: Optional[float] = None
    fumbles: Optional[int] = None
    fumbles_lost: Optional[int] = None
    fantasy_points: Optional[float] = None
    snaps: Optional[int] = None
    snap_pct: Optional[float] = None
    advanced_stats: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    source_timestamp: Optional[str] = None
    ingested_at: Optional[str] = None


class PlayerPerformancesResult(BaseModel):
    player: PlayerRecord
    performances: list[PerformanceRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class GameRecord(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: Optional[str] = None
    home_team: str
    away_team: str
    kickoff_time: Optional[str] = None
    venue: Optional[str] = None
    venue_location: Optional[dict[str, Any]] = None
    weather_conditions: Optional[dict[str, Any]] = None
    final_score: Optional[str] = None


class GamesResult(BaseModel):
    games: list[GameRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class DefenseRecord(BaseModel):
    team: str
    season: int
    week_through: int
    pass_yards_allowed: Optional[float] = None
    rush_yards_allowed: Optional[float] = None
    points_allowed: Optional[float] = None
    position_fantasy_points_allowed: Optional[dict[str, Any]] = None
    pressure_rate: Optional[float] = None
    coverage_grades: Optional[dict[str, Any]] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None


class GameContextResult(BaseModel):
    game: GameRecord
    home_defense: Optional[DefenseRecord] = None
    away_defense: Optional[DefenseRecord] = None
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class RosterResult(BaseModel):
    team: str
    include_all_positions: bool = False
    players: list[PlayerRecord] = Field(default_factory=list)
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)


class CacheStatusResult(BaseModel):
    database: dict[str, str]
    record_counts: dict[str, int]
    cached_seasons: list[int] = Field(default_factory=list)
    cached_weeks: dict[str, list[int]] = Field(default_factory=dict)
    available_domains: dict[str, bool]
    refresh: RefreshMetadata = Field(default_factory=RefreshMetadata)
