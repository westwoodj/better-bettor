"""SQLAlchemy 2.0 declarative ORM models for Gridiron Oracle."""

from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Boolean, Text, DateTime, JSON,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    espn_id: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True)
    nflverse_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    team: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    height: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    experience: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    game_stats: Mapped[list["PlayerGameStats"]] = relationship(back_populates="player")
    prop_lines: Mapped[list["PropLine"]] = relationship(back_populates="player")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="player")


class Game(Base):
    __tablename__ = "games"

    game_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    game_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    home_team: Mapped[str] = mapped_column(String(8))
    away_team: Mapped[str] = mapped_column(String(8))
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    weather_conditions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    final_score: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    game_stats: Mapped[list["PlayerGameStats"]] = relationship(back_populates="game")
    prop_lines: Mapped[list["PropLine"]] = relationship(back_populates="game")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="game")


class PlayerGameStats(Base):
    __tablename__ = "player_game_stats"

    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(32), ForeignKey("games.game_id"), primary_key=True)

    # Passing
    pass_completions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pass_attempts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pass_yards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pass_tds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    interceptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    passer_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Rushing
    rush_attempts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rush_yards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rush_tds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yards_per_carry: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Receiving
    receptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    targets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    receiving_yards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    receiving_tds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yards_per_reception: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # General
    fumbles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fumbles_lost: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fantasy_points: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snaps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    snap_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Flexible storage for advanced metrics
    advanced_stats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Source tracking
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped["Player"] = relationship(back_populates="game_stats")
    game: Mapped["Game"] = relationship(back_populates="game_stats")


class PropLine(Base):
    __tablename__ = "prop_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"))
    game_id: Mapped[Optional[str]] = mapped_column(String(32), ForeignKey("games.game_id"), nullable=True)
    market: Mapped[str] = mapped_column(String(64))
    line_value: Mapped[float] = mapped_column(Float)
    over_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    under_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sportsbook: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    consensus_line: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped["Player"] = relationship(back_populates="prop_lines")
    game: Mapped[Optional["Game"]] = relationship(back_populates="prop_lines")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"))
    game_id: Mapped[str] = mapped_column(String(32), ForeignKey("games.game_id"))
    predicted_stats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    recommended_props: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reasoning_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped["Player"] = relationship(back_populates="predictions")
    game: Mapped["Game"] = relationship(back_populates="predictions")


class DefenseProfile(Base):
    __tablename__ = "defense_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team: Mapped[str] = mapped_column(String(8))
    season: Mapped[int] = mapped_column(Integer)
    week_through: Mapped[int] = mapped_column(Integer)
    pass_yards_allowed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rush_yards_allowed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    points_allowed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_fantasy_points_allowed: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pressure_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    coverage_grades: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("team", "season", "week_through", "source", name="uq_defense_profile"),
    )
