"""CRUD repository classes for Gridiron Oracle database access."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .sa_models import (
    Player, Game, PlayerGameStats, PropLine, Prediction, DefenseProfile,
)


class PlayerRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, player_id: str, **kwargs) -> Player:
        player = self.session.get(Player, player_id)
        if player is None:
            player = Player(player_id=player_id, **kwargs)
            self.session.add(player)
        else:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(player, k, v)
        return player

    def get(self, player_id: str) -> Optional[Player]:
        return self.session.get(Player, player_id)

    def find_by_name(self, name: str) -> Optional[Player]:
        stmt = select(Player).where(Player.name == name)
        return self.session.execute(stmt).scalar_one_or_none()

    def find_by_name_fuzzy(self, name: str) -> Optional[Player]:
        """Case-insensitive partial match on player name."""
        stmt = select(Player).where(Player.name.ilike(f"%{name}%"))
        return self.session.execute(stmt).scalars().first()

    def find_by_espn_id(self, espn_id: str) -> Optional[Player]:
        stmt = select(Player).where(Player.espn_id == espn_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_team(self, team: str) -> list[Player]:
        stmt = select(Player).where(Player.team == team)
        return list(self.session.execute(stmt).scalars().all())


class GameRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, game_id: str, **kwargs) -> Game:
        game = self.session.get(Game, game_id)
        if game is None:
            game = Game(game_id=game_id, **kwargs)
            self.session.add(game)
        else:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(game, k, v)
        return game

    def get(self, game_id: str) -> Optional[Game]:
        return self.session.get(Game, game_id)

    def find_by_week(self, season: int, week: int) -> list[Game]:
        stmt = select(Game).where(Game.season == season, Game.week == week)
        return list(self.session.execute(stmt).scalars().all())

    def find_by_team(self, team: str, season: int) -> list[Game]:
        stmt = select(Game).where(
            Game.season == season,
            (Game.home_team == team) | (Game.away_team == team),
        )
        return list(self.session.execute(stmt).scalars().all())


class StatsRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, player_id: str, game_id: str, **kwargs) -> PlayerGameStats:
        stats = self.session.get(PlayerGameStats, (player_id, game_id))
        if stats is None:
            stats = PlayerGameStats(player_id=player_id, game_id=game_id, **kwargs)
            self.session.add(stats)
        else:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(stats, k, v)
        return stats

    def get(self, player_id: str, game_id: str) -> Optional[PlayerGameStats]:
        return self.session.get(PlayerGameStats, (player_id, game_id))

    def get_player_games(self, player_id: str, season: Optional[int] = None) -> list[PlayerGameStats]:
        stmt = select(PlayerGameStats).where(PlayerGameStats.player_id == player_id)
        if season is not None:
            stmt = stmt.join(Game).where(Game.season == season)
        return list(self.session.execute(stmt).scalars().all())

    def get_recent_games(self, player_id: str, limit: int = 5) -> list[PlayerGameStats]:
        stmt = (
            select(PlayerGameStats)
            .where(PlayerGameStats.player_id == player_id)
            .join(Game)
            .order_by(Game.week.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())


class PropLineRepo:
    def __init__(self, session: Session):
        self.session = session

    def add(self, **kwargs) -> PropLine:
        prop = PropLine(**kwargs)
        self.session.add(prop)
        return prop

    def get_for_player_game(self, player_id: str, game_id: str) -> list[PropLine]:
        stmt = select(PropLine).where(
            PropLine.player_id == player_id,
            PropLine.game_id == game_id,
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_for_player(self, player_id: str) -> list[PropLine]:
        stmt = select(PropLine).where(PropLine.player_id == player_id)
        return list(self.session.execute(stmt).scalars().all())


class PredictionRepo:
    def __init__(self, session: Session):
        self.session = session

    def add(self, **kwargs) -> Prediction:
        pred = Prediction(**kwargs)
        self.session.add(pred)
        return pred

    def get_latest(self, player_id: str, game_id: str) -> Optional[Prediction]:
        stmt = (
            select(Prediction)
            .where(Prediction.player_id == player_id, Prediction.game_id == game_id)
            .order_by(Prediction.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()


class DefenseProfileRepo:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, team: str, season: int, week_through: int, source: str = "nflverse", **kwargs) -> DefenseProfile:
        stmt = select(DefenseProfile).where(
            DefenseProfile.team == team,
            DefenseProfile.season == season,
            DefenseProfile.week_through == week_through,
            DefenseProfile.source == source,
        )
        profile = self.session.execute(stmt).scalar_one_or_none()
        if profile is None:
            profile = DefenseProfile(
                team=team, season=season, week_through=week_through, source=source, **kwargs,
            )
            self.session.add(profile)
        else:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(profile, k, v)
            profile.updated_at = datetime.now(timezone.utc)
        return profile

    def get(self, team: str, season: int, week_through: int) -> Optional[DefenseProfile]:
        stmt = select(DefenseProfile).where(
            DefenseProfile.team == team,
            DefenseProfile.season == season,
            DefenseProfile.week_through == week_through,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_latest(self, team: str, season: int) -> Optional[DefenseProfile]:
        stmt = (
            select(DefenseProfile)
            .where(DefenseProfile.team == team, DefenseProfile.season == season)
            .order_by(DefenseProfile.week_through.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
