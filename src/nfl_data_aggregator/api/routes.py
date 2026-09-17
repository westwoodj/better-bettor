"""API route handlers for Gridiron Oracle."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db.repository import (
    DefenseProfileRepo,
    GameRepo,
    PlayerRepo,
    PredictionRepo,
    StatsRepo,
)
from ..config.config import settings
from .app import get_db
from ..adapters.espn_api import NFLClient
from ..adapters.espn_stats_adapter import ESPNStatsAdapter
from .schemas import (
    BatchPredictionRequest,
    BatchPredictionResponse,
    DefenseProfileResponse,
    GameContextResponse,
    GameSearchResponse,
    GameSearchResult,
    GameStatRow,
    HealthResponse,
    PlayerResponse,
    PlayerSearchResponse,
    PlayerStatsResponse,
    PredictionResponse,
    PropRecommendation,
    PropRecommendationsResponse,
    RosterPlayerResponse,
    RosterResponse,
    StatPredictionSchema,
    TeamSearchResponse,
    TeamSearchResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


def _confidence_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _prediction_result_to_response(result, player_name: str | None = None) -> PredictionResponse:
    """Convert a PredictionResult dataclass to a PredictionResponse schema."""
    stats = []
    for stat_name, values in (result.predicted_stats or {}).items():
        if isinstance(values, dict):
            stats.append(StatPredictionSchema(
                stat_name=stat_name,
                floor=values.get("floor"),
                expected=values.get("expected"),
                ceiling=values.get("ceiling"),
            ))

    props = []
    for p in (result.prop_comparisons or []):
        props.append(PropRecommendation(
            market=p.get("market", ""),
            line=p.get("line", 0),
            predicted=p.get("predicted", 0),
            edge=p.get("edge", 0),
            recommendation=p.get("recommendation", ""),
            sportsbook=p.get("sportsbook"),
            player_id=result.player_id,
            player_name=player_name,
        ))

    hallucination_passed = None
    if result.hallucination_check is not None:
        hallucination_passed = result.hallucination_check.passed

    return PredictionResponse(
        player_id=result.player_id,
        player_name=player_name,
        game_id=result.game_id,
        predicted_stats=stats,
        confidence_score=result.confidence_score,
        confidence_grade=_confidence_grade(result.confidence_score),
        trend_analysis=result.trend_analysis,
        matchup_assessment=result.matchup_assessment,
        key_factors=result.key_factors,
        risk_factors=result.risk_factors,
        prop_comparisons=props,
        data_snapshot_hash=result.data_snapshot_hash,
        hallucination_passed=hallucination_passed,
    )


# --- Health ---

@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """Check system health: DB connectivity and DSPy configuration."""
    db_ok = False
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    dspy_configured = bool(
        getattr(settings, "ANTHROPIC_API_KEY", None)
        or getattr(settings, "OPENAI_API_KEY", None)
    )

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_ok=db_ok,
        dspy_configured=dspy_configured,
        version="0.2.0",
    )


# --- Single Player Prediction ---

@router.get("/players/{player_id}/prediction", response_model=PredictionResponse)
def get_player_prediction(
    player_id: str,
    game_id: str = Query(..., description="Game ID to predict for"),
    db: Session = Depends(get_db),
):
    """Run the prediction pipeline for a single player."""
    player_repo = PlayerRepo(db)
    player = player_repo.get(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    game_repo = GameRepo(db)
    game = game_repo.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

    try:
        from ..services.prediction_service import PredictionService

        service = PredictionService(session=db)
        result = service.predict_player(player_id, game_id)
        return _prediction_result_to_response(result, player_name=player.name)
    except Exception as exc:
        logger.exception("Prediction pipeline failed for player=%s game=%s", player_id, game_id)
        raise HTTPException(status_code=500, detail=str(exc))


# --- Batch Predictions ---

@router.post("/predictions/batch", response_model=BatchPredictionResponse)
def batch_predictions(
    request: BatchPredictionRequest,
    db: Session = Depends(get_db),
):
    """Run predictions for multiple player/game pairs."""
    from ..services.prediction_service import PredictionService

    service = PredictionService(session=db)
    results = []
    failed = 0

    for item in request.predictions:
        player_repo = PlayerRepo(db)
        player = player_repo.get(item.player_id)
        if player is None:
            failed += 1
            continue
        try:
            result = service.predict_player(item.player_id, item.game_id)
            results.append(_prediction_result_to_response(result, player_name=player.name))
        except Exception:
            logger.exception("Batch prediction failed for player=%s game=%s", item.player_id, item.game_id)
            failed += 1

    return BatchPredictionResponse(
        results=results,
        total=len(request.predictions),
        succeeded=len(results),
        failed=failed,
    )


# --- Prop Recommendations ---

@router.get("/props/recommendations", response_model=PropRecommendationsResponse)
def get_prop_recommendations(
    game_id: Optional[str] = Query(None, description="Filter by game ID"),
    min_edge: Optional[float] = Query(None, description="Minimum edge threshold"),
    sportsbook: Optional[str] = Query(None, description="Filter by sportsbook"),
    db: Session = Depends(get_db),
):
    """Get prop bet recommendations from stored predictions."""
    from sqlalchemy import select
    from ..db.sa_models import Prediction

    stmt = select(Prediction)
    if game_id:
        stmt = stmt.where(Prediction.game_id == game_id)
    predictions = list(db.execute(stmt).scalars().all())

    recommendations = []
    for pred in predictions:
        if not pred.recommended_props:
            continue

        player_repo = PlayerRepo(db)
        player = player_repo.get(pred.player_id)
        player_name = player.name if player else None

        for prop in pred.recommended_props:
            edge = prop.get("edge", 0)
            prop_sportsbook = prop.get("sportsbook")

            if min_edge is not None and edge < min_edge:
                continue
            if sportsbook is not None and prop_sportsbook != sportsbook:
                continue

            recommendations.append(PropRecommendation(
                market=prop.get("market", ""),
                line=prop.get("line", 0),
                predicted=prop.get("predicted", 0),
                edge=edge,
                recommendation=prop.get("recommendation", ""),
                sportsbook=prop_sportsbook,
                player_id=pred.player_id,
                player_name=player_name,
            ))

    return PropRecommendationsResponse(recommendations=recommendations)


@router.get("/props/recommendations/{player_id}", response_model=PropRecommendationsResponse)
def get_player_props(
    player_id: str,
    game_id: Optional[str] = Query(None, description="Filter by game ID"),
    db: Session = Depends(get_db),
):
    """Get prop recommendations for a specific player."""
    player_repo = PlayerRepo(db)
    player = player_repo.get(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    prediction_repo = PredictionRepo(db)

    if game_id:
        pred = prediction_repo.get_latest(player_id, game_id)
        predictions = [pred] if pred else []
    else:
        from sqlalchemy import select
        from ..db.sa_models import Prediction

        stmt = (
            select(Prediction)
            .where(Prediction.player_id == player_id)
            .order_by(Prediction.created_at.desc())
        )
        predictions = list(db.execute(stmt).scalars().all())

    recommendations = []
    for pred in predictions:
        if not pred.recommended_props:
            continue
        for prop in pred.recommended_props:
            recommendations.append(PropRecommendation(
                market=prop.get("market", ""),
                line=prop.get("line", 0),
                predicted=prop.get("predicted", 0),
                edge=prop.get("edge", 0),
                recommendation=prop.get("recommendation", ""),
                sportsbook=prop.get("sportsbook"),
                player_id=player_id,
                player_name=player.name,
            ))

    return PropRecommendationsResponse(recommendations=recommendations)


# --- Player Stats ---

@router.get("/players/{player_id}/stats", response_model=PlayerStatsResponse)
def get_player_stats(
    player_id: str,
    season: Optional[int] = Query(None, description="Filter by season"),
    db: Session = Depends(get_db),
):
    """Get historical stats for a player."""
    player_repo = PlayerRepo(db)
    player = player_repo.get(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    stats_repo = StatsRepo(db)
    game_stats = stats_repo.get_player_games(player_id, season=season)

    game_repo = GameRepo(db)
    rows = []
    for gs in game_stats:
        game = game_repo.get(gs.game_id)
        opponent = None
        game_season = None
        game_week = None
        if game:
            game_season = game.season
            game_week = game.week
            if game.home_team == player.team:
                opponent = game.away_team
            else:
                opponent = game.home_team

        rows.append(GameStatRow(
            game_id=gs.game_id,
            season=game_season,
            week=game_week,
            opponent=opponent,
            pass_completions=gs.pass_completions,
            pass_attempts=gs.pass_attempts,
            pass_yards=gs.pass_yards,
            pass_tds=gs.pass_tds,
            interceptions=gs.interceptions,
            rush_attempts=gs.rush_attempts,
            rush_yards=gs.rush_yards,
            rush_tds=gs.rush_tds,
            receptions=gs.receptions,
            targets=gs.targets,
            receiving_yards=gs.receiving_yards,
            receiving_tds=gs.receiving_tds,
            fumbles=gs.fumbles,
            fantasy_points=gs.fantasy_points,
        ))

    return PlayerStatsResponse(
        player=PlayerResponse(
            player_id=player.player_id,
            name=player.name,
            team=player.team,
            position=player.position,
            status=player.status,
        ),
        games=rows,
    )


# --- Game Context ---

@router.get("/games/{game_id}/context", response_model=GameContextResponse)
def get_game_context(
    game_id: str,
    db: Session = Depends(get_db),
):
    """Get game context including defense profiles and weather."""
    game_repo = GameRepo(db)
    game = game_repo.get(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

    defense_repo = DefenseProfileRepo(db)
    home_def = defense_repo.get_latest(game.home_team, game.season)
    away_def = defense_repo.get_latest(game.away_team, game.season)

    home_defense = None
    if home_def:
        home_defense = DefenseProfileResponse(
            team=home_def.team,
            season=home_def.season,
            week_through=home_def.week_through,
            pass_yards_allowed=home_def.pass_yards_allowed,
            rush_yards_allowed=home_def.rush_yards_allowed,
            points_allowed=home_def.points_allowed,
            pressure_rate=home_def.pressure_rate,
        )

    away_defense = None
    if away_def:
        away_defense = DefenseProfileResponse(
            team=away_def.team,
            season=away_def.season,
            week_through=away_def.week_through,
            pass_yards_allowed=away_def.pass_yards_allowed,
            rush_yards_allowed=away_def.rush_yards_allowed,
            points_allowed=away_def.points_allowed,
            pressure_rate=away_def.pressure_rate,
        )

    return GameContextResponse(
        game_id=game.game_id,
        season=game.season,
        week=game.week,
        game_type=game.game_type,
        home_team=game.home_team,
        away_team=game.away_team,
        venue=game.venue,
        weather_conditions=game.weather_conditions,
        home_defense=home_defense,
        away_defense=away_defense,
    )


# --- Lookup / Search Endpoints ---

_espn_client: NFLClient | None = None


def _get_espn_client() -> NFLClient:
    """Lazily instantiate a shared NFLClient (lightweight, loads local JSON only)."""
    global _espn_client
    if _espn_client is None:
        _espn_client = NFLClient()
    return _espn_client


@router.get("/teams/search", response_model=TeamSearchResponse)
def search_teams(
    q: str = Query(..., min_length=1, description="Team name, abbreviation, or city"),
):
    """Search NFL teams by name, abbreviation, or city.

    Uses local all-teams.json — no network call required.
    """
    client = _get_espn_client()
    data = client._load_all_teams()
    if not data:
        return TeamSearchResponse(results=[])

    query_lower = q.lower()
    fields = ("displayName", "shortDisplayName", "name", "abbreviation", "slug", "nickname", "location")
    results: list[TeamSearchResult] = []
    seen_ids: set[str] = set()

    # Scan all teams for partial matches
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []) or []:
            for t in league.get("teams", []):
                team = t.get("team") or {}
                team_id = str(team.get("id", ""))
                if team_id in seen_ids:
                    continue
                for key in fields:
                    val = team.get(key)
                    if val and query_lower in val.lower():
                        seen_ids.add(team_id)
                        results.append(TeamSearchResult(
                            id=team_id,
                            abbreviation=team.get("abbreviation", ""),
                            displayName=team.get("displayName", ""),
                            shortDisplayName=team.get("shortDisplayName"),
                            location=team.get("location"),
                            nickname=team.get("nickname"),
                        ))
                        break

    return TeamSearchResponse(results=results)


@router.get("/teams/{team_abbr}/roster", response_model=RosterResponse)
def get_team_roster(
    team_abbr: str,
    db: Session = Depends(get_db),
):
    """List skill-position players on a team. Checks DB first, falls back to ESPN."""
    player_repo = PlayerRepo(db)
    db_players = player_repo.list_by_team(team_abbr.upper())

    if db_players:
        roster_players = [
            RosterPlayerResponse(
                player_id=p.player_id,
                espn_id=p.espn_id,
                name=p.name,
                team=p.team,
                position=p.position,
                status=p.status,
                height=p.height,
                weight=p.weight,
                experience=p.experience,
            )
            for p in db_players
        ]
        return RosterResponse(team=team_abbr.upper(), players=roster_players)

    # Fallback: ESPN roster via network
    client = _get_espn_client()
    team_info = client.find_team_by_name(team_abbr)
    if not team_info:
        raise HTTPException(status_code=404, detail=f"Team '{team_abbr}' not found")

    team_id = team_info.get("id")
    if not team_id:
        raise HTTPException(status_code=404, detail=f"Team '{team_abbr}' has no ESPN ID")

    # Only use a local file when it is actually roster-specific. The generic
    # local-data heuristic must not turn all-teams.json into a roster payload.
    roster_path = client._find_local_data(
        "football",
        "nfl",
        f"/apis/site/v2/sports/football/nfl/teams/{team_id}/roster",
    )
    try:
        roster_data = client.roster(team_id, force=roster_path is None)
    except Exception as exc:
        logger.exception("Failed to fetch roster for team %s", team_abbr)
        raise HTTPException(status_code=502, detail=f"Failed to fetch roster from ESPN: {exc}")

    adapter = ESPNStatsAdapter(client)
    abbr = team_info.get("abbreviation", team_abbr.upper())
    extracted = adapter.extract_players_from_roster(roster_data, abbr)

    # Seed the DB as part of the network fallback so subsequent requests use
    # the DB-first path. Player IDs are ESPN IDs and are stable across refreshes.
    for player in extracted:
        player_id = player.pop("player_id")
        player_repo.upsert(player_id, **player)
    if extracted:
        db.commit()

    roster_players = [
        RosterPlayerResponse(
            player_id=p["player_id"],
            espn_id=p.get("espn_id"),
            name=p["name"],
            team=p.get("team"),
            position=p.get("position"),
            status=p.get("status"),
            height=p.get("height"),
            weight=p.get("weight"),
            experience=p.get("experience"),
        )
        for p in extracted
    ]
    return RosterResponse(team=abbr, players=roster_players)


@router.get("/players/search", response_model=PlayerSearchResponse)
def search_players(
    q: str = Query(..., min_length=1, description="Player name to search"),
    team: Optional[str] = Query(None, description="Filter by team abbreviation"),
    db: Session = Depends(get_db),
):
    """Search players by name (fuzzy match). Optionally filter by team."""
    from sqlalchemy import select
    from ..db.sa_models import Player

    query = q.strip()
    stmt = select(Player).where(Player.name.ilike(f"%{query}%"))
    if team:
        stmt = stmt.where(Player.team == team.upper())
    players = list(db.execute(stmt).scalars().all())

    results = [
        PlayerResponse(
            player_id=p.player_id,
            name=p.name,
            team=p.team,
            position=p.position,
            status=p.status,
        )
        for p in players
    ]
    return PlayerSearchResponse(results=results)


@router.get("/games/search", response_model=GameSearchResponse)
def search_games(
    team: Optional[str] = Query(None, description="Team abbreviation"),
    season: Optional[int] = Query(None, description="Season year"),
    week: Optional[int] = Query(None, description="Week number"),
    db: Session = Depends(get_db),
):
    """Search games by team, season, and/or week. At least one filter required."""
    if not team and season is None and week is None:
        raise HTTPException(
            status_code=400,
            detail="At least one query parameter (team, season, week) is required",
        )

    game_repo = GameRepo(db)
    games: list = []

    if season is not None and week is not None:
        games = game_repo.find_by_week(season, week)
        if team:
            team_upper = team.upper()
            games = [g for g in games if g.home_team == team_upper or g.away_team == team_upper]
    elif team and season is not None:
        games = game_repo.find_by_team(team.upper(), season)
    elif team:
        # Team without season — search across all seasons via raw query
        from sqlalchemy import select
        from ..db.sa_models import Game

        stmt = select(Game).where(
            (Game.home_team == team.upper()) | (Game.away_team == team.upper())
        )
        games = list(db.execute(stmt).scalars().all())
    elif season is not None:
        # Season without team/week — all games in the season
        from sqlalchemy import select
        from ..db.sa_models import Game

        stmt = select(Game).where(Game.season == season)
        games = list(db.execute(stmt).scalars().all())
    elif week is not None:
        # Week without season — not very useful but handle it
        from sqlalchemy import select
        from ..db.sa_models import Game

        stmt = select(Game).where(Game.week == week)
        games = list(db.execute(stmt).scalars().all())

    results = [
        GameSearchResult(
            game_id=g.game_id,
            season=g.season,
            week=g.week,
            game_type=g.game_type,
            home_team=g.home_team,
            away_team=g.away_team,
            venue=g.venue,
            kickoff_time=str(g.kickoff_time) if g.kickoff_time else None,
        )
        for g in games
    ]
    return GameSearchResponse(results=results)
