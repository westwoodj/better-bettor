"""Pydantic v2 request/response schemas for the Gridiron Oracle REST API."""


from pydantic import BaseModel

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
    team: str | None = None
    position: str | None = None
    status: str | None = None


class PlayerSearchResponse(BaseModel):
    results: list[PlayerResponse] = []


# --- Teams ---

class TeamSearchResult(BaseModel):
    id: str
    abbreviation: str
    displayName: str
    shortDisplayName: str | None = None
    location: str | None = None
    nickname: str | None = None


class TeamSearchResponse(BaseModel):
    results: list[TeamSearchResult] = []


# --- Roster ---

class RosterPlayerResponse(BaseModel):
    player_id: str
    espn_id: str | None = None
    name: str
    team: str | None = None
    position: str | None = None
    status: str | None = None
    height: str | None = None
    weight: int | None = None
    experience: int | None = None


class RosterResponse(BaseModel):
    team: str
    players: list[RosterPlayerResponse] = []


# --- Game Search ---

class GameSearchResult(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: str | None = None
    home_team: str
    away_team: str
    venue: str | None = None
    kickoff_time: str | None = None


class GameSearchResponse(BaseModel):
    results: list[GameSearchResult] = []


# --- Game Context ---

class DefenseProfileResponse(BaseModel):
    team: str
    season: int
    week_through: int
    pass_yards_allowed: float | None = None
    rush_yards_allowed: float | None = None
    points_allowed: float | None = None
    pressure_rate: float | None = None


class GameContextResponse(BaseModel):
    game_id: str
    season: int
    week: int
    game_type: str | None = None
    home_team: str
    away_team: str
    venue: str | None = None
    weather_conditions: dict | None = None
    home_defense: DefenseProfileResponse | None = None
    away_defense: DefenseProfileResponse | None = None


# --- Stats ---

class GameStatRow(BaseModel):
    game_id: str
    season: int | None = None
    week: int | None = None
    opponent: str | None = None
    pass_completions: int | None = None
    pass_attempts: int | None = None
    pass_yards: int | None = None
    pass_tds: int | None = None
    interceptions: int | None = None
    rush_attempts: int | None = None
    rush_yards: int | None = None
    rush_tds: int | None = None
    receptions: int | None = None
    targets: int | None = None
    receiving_yards: int | None = None
    receiving_tds: int | None = None
    fumbles: int | None = None
    fantasy_points: float | None = None


class PlayerStatsResponse(BaseModel):
    player: PlayerResponse
    games: list[GameStatRow] = []


# --- Predictions ---

class StatPredictionSchema(BaseModel):
    stat_name: str
    floor: float | None = None
    expected: float | None = None
    ceiling: float | None = None


class PredictionResponse(BaseModel):
    player_id: str
    player_name: str | None = None
    game_id: str
    predicted_stats: list[StatPredictionSchema] = []
    confidence_score: float = 0.0
    confidence_grade: str | None = None
    trend_analysis: str | None = None
    matchup_assessment: str | None = None
    key_factors: str | None = None
    risk_factors: str | None = None
    prop_comparisons: list[PropRecommendation] = []
    data_snapshot_hash: str | None = None
    hallucination_passed: bool | None = None


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
    sportsbook: str | None = None
    player_id: str | None = None
    player_name: str | None = None


class PropRecommendationsResponse(BaseModel):
    recommendations: list[PropRecommendation] = []


# --- Errors ---

class ErrorResponse(BaseModel):
    detail: str
