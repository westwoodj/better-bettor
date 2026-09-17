"""Database-first query and targeted refresh service used by the MCP server."""

from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..adapters.espn_api import NFLClient
from ..adapters.espn_stats_adapter import SKILL_POSITIONS
from ..db.repository import DefenseProfileRepo, GameRepo, PlayerRepo
from ..db.sa_models import DefenseProfile, Game, Player, PlayerGameStats
from ..ingestion.espn_ingestor import ESPNIngestor
from ..mcp.schemas import (
    CacheStatusResult,
    DefenseRecord,
    GameContextResult,
    GameRecord,
    GamesResult,
    PerformanceRecord,
    PlayerPerformancesResult,
    PlayerRecord,
    PlayerSearchResult,
    RefreshMetadata,
    RosterResult,
)


class DataQueryError(ValueError):
    """A concise, user-facing data query or refresh failure."""


class DataQueryService:
    """Query persisted NFL data and explicitly refresh bounded ESPN resources."""

    def __init__(self, session: Session, espn_client: NFLClient | None = None):
        self.session = session
        self.client = espn_client or NFLClient()

    def get_cache_status(self) -> CacheStatusResult:
        models = {
            "players": Player,
            "games": Game,
            "player_game_stats": PlayerGameStats,
            "defense_profiles": DefenseProfile,
        }
        counts = {
            name: int(self.session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in models.items()
        }
        seasons = list(self.session.scalars(select(Game.season).distinct().order_by(Game.season)).all())
        weeks: dict[str, list[int]] = {}
        for season in seasons:
            values = self.session.scalars(
                select(Game.week).where(Game.season == season).distinct().order_by(Game.week)
            ).all()
            weeks[str(season)] = list(values)

        return CacheStatusResult(
            database=self._database_identity(),
            record_counts=counts,
            cached_seasons=seasons,
            cached_weeks=weeks,
            available_domains={
                "players": counts["players"] > 0,
                "performances": counts["player_game_stats"] > 0,
                "games": counts["games"] > 0,
                "rosters": counts["players"] > 0,
                "game_context": counts["games"] > 0,
                "defense_profiles": counts["defense_profiles"] > 0,
            },
        )

    def search_players(
        self,
        query: str,
        *,
        team: str | None = None,
        position: str | None = None,
        limit: int = 25,
    ) -> PlayerSearchResult:
        limit = _validate_limit(limit)
        query = query.strip()
        if not query:
            raise DataQueryError("query must not be empty")
        stmt = select(Player).where(Player.name.ilike(f"%{query}%"))
        if team:
            stmt = stmt.where(Player.team == team.upper())
        if position:
            stmt = stmt.where(Player.position == position.upper())
        stmt = stmt.order_by(Player.name.asc(), Player.player_id.asc()).limit(limit)
        players = list(self.session.scalars(stmt).all())
        return PlayerSearchResult(query=query, players=[_player_record(player) for player in players])

    def get_player_performances(
        self,
        player_id: str,
        *,
        season: int | None = None,
        limit: int = 20,
        force: bool = False,
    ) -> PlayerPerformancesResult:
        limit = _validate_limit(limit)
        player = PlayerRepo(self.session).get(player_id)
        if player is None:
            raise DataQueryError(f"Player {player_id} not found")

        refresh = RefreshMetadata(force_requested=force)
        if force:
            if season is None:
                raise DataQueryError("season is required when force=true for player performances")
            counts = self._run_refresh(
                lambda ingestor: ingestor.ingest_player_season(
                    player_id, season, force=True, commit=False
                )
            )
            refresh = _refresh_metadata(counts)

        stmt = (
            select(PlayerGameStats, Game)
            .join(Game, Game.game_id == PlayerGameStats.game_id)
            .where(PlayerGameStats.player_id == player_id)
        )
        if season is not None:
            stmt = stmt.where(Game.season == season)
        stmt = stmt.order_by(
            Game.season.desc(), Game.week.desc(), Game.kickoff_time.desc(), Game.game_id.asc()
        ).limit(limit)
        rows = self.session.execute(stmt).all()
        performances = [_performance_record(stats, game, player) for stats, game in rows]
        return PlayerPerformancesResult(
            player=_player_record(player),
            performances=performances,
            refresh=refresh,
        )

    def list_games(
        self,
        season: int,
        *,
        week: int | None = None,
        team: str | None = None,
        limit: int = 50,
        force: bool = False,
    ) -> GamesResult:
        limit = _validate_limit(limit)
        refresh = RefreshMetadata(force_requested=force)
        if force:
            if week is None:
                raise DataQueryError("week is required when force=true for game listings")
            counts = self._run_refresh(
                lambda ingestor: ingestor.ingest_week(
                    season, week, force=True, strict=True, commit=False
                )
            )
            refresh = _refresh_metadata(counts)

        stmt = select(Game).where(Game.season == season)
        if week is not None:
            stmt = stmt.where(Game.week == week)
        if team:
            abbr = team.upper()
            stmt = stmt.where(or_(Game.home_team == abbr, Game.away_team == abbr))
        stmt = stmt.order_by(
            Game.week.desc(), Game.kickoff_time.desc(), Game.game_id.asc()
        ).limit(limit)
        games = list(self.session.scalars(stmt).all())
        return GamesResult(games=[_game_record(game) for game in games], refresh=refresh)

    def get_game_context(self, game_id: str, *, force: bool = False) -> GameContextResult:
        refresh = RefreshMetadata(force_requested=force)
        if force:
            counts = self._run_refresh(
                lambda ingestor: ingestor.ingest_game(game_id, force=True, commit=False)
            )
            refresh = _refresh_metadata(counts)

        game = GameRepo(self.session).get(game_id)
        if game is None:
            raise DataQueryError(f"Game {game_id} not found")
        defenses = DefenseProfileRepo(self.session)
        return GameContextResult(
            game=_game_record(game),
            home_defense=_defense_record(defenses.get_latest(game.home_team, game.season)),
            away_defense=_defense_record(defenses.get_latest(game.away_team, game.season)),
            refresh=refresh,
        )

    def get_roster(
        self,
        team: str,
        *,
        include_all_positions: bool = False,
        force: bool = False,
    ) -> RosterResult:
        team_info = self.client.find_team_by_name(team)
        if team_info is None:
            raise DataQueryError(f"NFL team {team!r} not found")
        team_abbr = str(team_info.get("abbreviation") or team).upper()

        refresh = RefreshMetadata(force_requested=force)
        if force:
            team_id = team_info.get("id")
            if not team_id:
                raise DataQueryError(f"NFL team {team!r} has no ESPN ID")
            counts = self._run_refresh(
                lambda ingestor: ingestor.ingest_roster(
                    str(team_id),
                    force=True,
                    include_all_positions=include_all_positions,
                    reconcile=True,
                    commit=False,
                )
            )
            refresh = _refresh_metadata(counts)
        elif include_all_positions:
            refresh.warnings.append(
                "Full-roster cache completeness is not guaranteed until force=true has populated it"
            )

        stmt = select(Player).where(Player.team == team_abbr)
        if not include_all_positions:
            stmt = stmt.where(Player.position.in_(sorted(SKILL_POSITIONS)))
        stmt = stmt.order_by(Player.position.asc(), Player.name.asc(), Player.player_id.asc())
        players = list(self.session.scalars(stmt).all())
        return RosterResult(
            team=team_abbr,
            include_all_positions=include_all_positions,
            players=[_player_record(player) for player in players],
            refresh=refresh,
        )

    def _run_refresh(self, operation) -> dict[str, int]:
        try:
            result = operation(ESPNIngestor(self.session, self.client))
            self.session.commit()
            return {key: int(value) for key, value in result.items() if isinstance(value, int)}
        except DataQueryError:
            self.session.rollback()
            raise
        except Exception as exc:
            self.session.rollback()
            raise DataQueryError(f"ESPN refresh failed: {exc}") from exc

    def _database_identity(self) -> dict[str, str]:
        bind = self.session.get_bind()
        url = bind.url
        identity = {"dialect": url.get_backend_name()}
        if url.database and url.database != ":memory:":
            identity["database"] = Path(url.database).name if url.get_backend_name() == "sqlite" else url.database
        if url.host:
            identity["host"] = url.host
        return identity


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise DataQueryError("limit must be between 1 and 100")
    return limit


def _refresh_metadata(counts: dict[str, int]) -> RefreshMetadata:
    return RefreshMetadata(
        force_requested=True,
        refreshed=True,
        source="espn",
        records_written=counts,
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _player_record(player: Player) -> PlayerRecord:
    return PlayerRecord(
        player_id=player.player_id,
        espn_id=player.espn_id,
        nflverse_id=player.nflverse_id,
        name=player.name,
        team=player.team,
        position=player.position,
        status=player.status,
        height=player.height,
        weight=player.weight,
        experience=player.experience,
    )


def _performance_record(stats: PlayerGameStats, game: Game, player: Player) -> PerformanceRecord:
    opponent = None
    home_away = None
    if player.team == game.home_team:
        opponent, home_away = game.away_team, "home"
    elif player.team == game.away_team:
        opponent, home_away = game.home_team, "away"
    values = {
        column.name: getattr(stats, column.name)
        for column in PlayerGameStats.__table__.columns
        if column.name not in {"player_id", "game_id"}
    }
    values.update(
        game_id=game.game_id,
        season=game.season,
        week=game.week,
        opponent=opponent,
        home_away=home_away,
        kickoff_time=_iso(game.kickoff_time),
        source_timestamp=_iso(stats.source_timestamp),
        ingested_at=_iso(stats.ingested_at),
    )
    return PerformanceRecord(**values)


def _game_record(game: Game) -> GameRecord:
    return GameRecord(
        game_id=game.game_id,
        season=game.season,
        week=game.week,
        game_type=game.game_type,
        home_team=game.home_team,
        away_team=game.away_team,
        kickoff_time=_iso(game.kickoff_time),
        venue=game.venue,
        venue_location=game.venue_location,
        weather_conditions=game.weather_conditions,
        final_score=game.final_score,
    )


def _defense_record(profile: DefenseProfile | None) -> DefenseRecord | None:
    if profile is None:
        return None
    return DefenseRecord(
        team=profile.team,
        season=profile.season,
        week_through=profile.week_through,
        pass_yards_allowed=profile.pass_yards_allowed,
        rush_yards_allowed=profile.rush_yards_allowed,
        points_allowed=profile.points_allowed,
        position_fantasy_points_allowed=profile.position_fantasy_points_allowed,
        pressure_rate=profile.pressure_rate,
        coverage_grades=profile.coverage_grades,
        source=profile.source,
        updated_at=_iso(profile.updated_at),
    )
