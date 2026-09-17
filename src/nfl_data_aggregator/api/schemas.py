"""Pydantic v2 request/response schemas for the Gridiron Oracle REST API."""

from typing import Optional

from pydantic import BaseModel, Field


# --- Health ---

class HealthResponse(BaseModel):
    status: str = "ok"
    db_ok: bool = False
    dspy_configured: bool = False
    version: str = ""


# --- Players ---

class PlayerResponse(BaseModel):
    player_id: str
    name: str
    team: Optional[str] = None
    position: Optional[str] = None
    status: Optional[str] = None


class PlayerSearchResponse(BaseModel):
    results: list[PlayerResponse] = []


# --- Teams ---

class TeamSearchResult(BaseModel):
    id: str
    abbreviation: str
    displayName: str
    shortDisplayName: Optional[str] = None
    location: Optional[str] = None
    nickname: Optional[str] = None


class TeamSearchResponse(BaseModel):
    results: list[TeamSearchResult] = []


# --- Roster ---

class RosterPlayerResponse(BaseModel):
    player_id: str
    espn_id: Optional[str] = None
    name: str
    team: Optional[str] = None
    position: Optional[str] = None
    status: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[int] = None
    experience: Optional[int] = None


class RosterResponse(BaseModel):
    team: str
    players: list[RosterPlayerResponse] = []


# --- Game Search ---

class GameSearchResult(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: Optional[str] = None
    home_team: str
    away_team: str
    venue: Optional[str] = None
    kickoff_time: Optional[str] = None


class GameSearchResponse(BaseModel):
    results: list[GameSearchResult] = []


# --- Game Context ---

class DefenseProfileResponse(BaseModel):
    team: str
    season: int
    week_through: int
    pass_yards_allowed: Optional[float] = None
    rush_yards_allowed: Optional[float] = None
    points_allowed: Optional[float] = None
    pressure_rate: Optional[float] = None


class GameContextResponse(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: Optional[str] = None
    home_team: str
    away_team: str
    venue: Optional[str] = None
    weather_conditions: Optional[dict] = None
    home_defense: Optional[DefenseProfileResponse] = None
    away_defense: Optional[DefenseProfileResponse] = None


# --- Stats ---

class GameStatRow(BaseModel):
    game_id: str
    season: Optional[int] = None
    week: Optional[int] = None
    opponent: Optional[str] = None
    pass_completions: Optional[int] = None
    pass_attempts: Optional[int] = None
    pass_yards: Optional[int] = None
    pass_tds: Optional[int] = None
    interceptions: Optional[int] = None
    rush_attempts: Optional[int] = None
    rush_yards: Optional[int] = None
    rush_tds: Optional[int] = None
    receptions: Optional[int] = None
    targets: Optional[int] = None
    receiving_yards: Optional[int] = None
    receiving_tds: Optional[int] = None
    fumbles: Optional[int] = None
    fantasy_points: Optional[float] = None


class PlayerStatsResponse(BaseModel):
    player: PlayerResponse
    games: list[GameStatRow] = []


# --- Predictions ---

class StatPredictionSchema(BaseModel):
    stat_name: str
    floor: Optional[float] = None
    expected: Optional[float] = None
    ceiling: Optional[float] = None


class PredictionResponse(BaseModel):
    player_id: str
    player_name: Optional[str] = None
    game_id: str
    predicted_stats: list[StatPredictionSchema] = []
    confidence_score: float = 0.0
    confidence_grade: Optional[str] = None
    trend_analysis: Optional[str] = None
    matchup_assessment: Optional[str] = None
    key_factors: Optional[str] = None
    risk_factors: Optional[str] = None
    prop_comparisons: list["PropRecommendation"] = []
    data_snapshot_hash: Optional[str] = None
    hallucination_passed: Optional[bool] = None


class BatchPredictionItem(BaseModel):
    player_id: str
    game_id: str


class BatchPredictionRequest(BaseModel):
    predictions: list[BatchPredictionItem]


class BatchPredictionResponse(BaseModel):
    results: list[PredictionResponse] = []
    total: int = 0
    succeeded: int = 0
    failed: int = 0


# --- Props ---

class PropRecommendation(BaseModel):
    market: str
    line: float
    predicted: float
    edge: float
    recommendation: str
    sportsbook: Optional[str] = None
    player_id: Optional[str] = None
    player_name: Optional[str] = None


class PropRecommendationsResponse(BaseModel):
    recommendations: list[PropRecommendation] = []


# --- Errors ---

class ErrorResponse(BaseModel):
    detail: str
