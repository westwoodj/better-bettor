"""SQLAlchemy 2.0 declarative ORM models for Gridiron Oracle."""

from datetime import UTC, datetime


def _utcnow():
    return datetime.now(UTC)

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    player_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    espn_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    nflverse_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(128))
    team: Mapped[str | None] = mapped_column(String(8), nullable=True)
    position: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    height: Mapped[str | None] = mapped_column(String(8), nullable=True)
    weight: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience: Mapped[int | None] = mapped_column(Integer, nullable=True)

    game_stats: Mapped[list[PlayerGameStats]] = relationship(back_populates="player")
    prop_lines: Mapped[list[PropLine]] = relationship(back_populates="player")
    predictions: Mapped[list[Prediction]] = relationship(back_populates="player")
    odds_lines: Mapped[list[OddsLine]] = relationship(back_populates="player")


class Game(Base):
    __tablename__ = "games"

    game_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    game_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    home_team: Mapped[str] = mapped_column(String(8))
    away_team: Mapped[str] = mapped_column(String(8))
    kickoff_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    venue_location: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    weather_conditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_score: Mapped[str | None] = mapped_column(String(16), nullable=True)

    game_stats: Mapped[list[PlayerGameStats]] = relationship(back_populates="game")
    prop_lines: Mapped[list[PropLine]] = relationship(back_populates="game")
    predictions: Mapped[list[Prediction]] = relationship(back_populates="game")
    odds_event: Mapped[OddsEvent | None] = relationship(back_populates="game", uselist=False)


class OddsEvent(Base):
    __tablename__ = "odds_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sport_key: Mapped[str] = mapped_column(String(64), index=True)
    sport_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commence_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    home_team: Mapped[str] = mapped_column(String(128))
    away_team: Mapped[str] = mapped_column(String(128))
    game_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("games.game_id"), unique=True, nullable=True
    )
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    game: Mapped[Game | None] = relationship(back_populates="odds_event")
    snapshots: Mapped[list[OddsSnapshot]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_odds_events_sport_commence", "sport_key", "commence_time"),
    )


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), ForeignKey("odds_events.event_id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    request_signature: Mapped[str] = mapped_column(String(64))
    requested_markets: Mapped[list] = mapped_column(JSON)
    regions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    bookmakers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    odds_format: Mapped[str] = mapped_column(String(16), default="american")
    outcome_count: Mapped[int] = mapped_column(Integer, default=0)
    requests_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_last: Mapped[int | None] = mapped_column(Integer, nullable=True)

    event: Mapped[OddsEvent] = relationship(back_populates="snapshots")
    lines: Mapped[list[OddsLine]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_odds_snapshots_event_fetched", "event_id", "fetched_at"),
        Index(
            "ix_odds_snapshots_event_signature_fetched",
            "event_id",
            "request_signature",
            "fetched_at",
        ),
    )


class OddsLine(Base):
    __tablename__ = "odds_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, ForeignKey("odds_snapshots.id"))
    bookmaker_key: Mapped[str] = mapped_column(String(64))
    bookmaker_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_key: Mapped[str] = mapped_column(String(96))
    market_last_update: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_name: Mapped[str] = mapped_column(String(128))
    participant: Mapped[str | None] = mapped_column(String(160), nullable=True)
    price: Mapped[float] = mapped_column(Float)
    point: Mapped[float | None] = mapped_column(Float, nullable=True)
    player_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("players.player_id"), nullable=True
    )
    extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    snapshot: Mapped[OddsSnapshot] = relationship(back_populates="lines")
    player: Mapped[Player | None] = relationship(back_populates="odds_lines")

    __table_args__ = (
        Index("ix_odds_lines_snapshot_market", "snapshot_id", "market_key"),
        Index("ix_odds_lines_bookmaker", "bookmaker_key"),
        Index("ix_odds_lines_participant", "participant"),
    )


class PlayerGameStats(Base):
    __tablename__ = "player_game_stats"

    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"), primary_key=True)
    game_id: Mapped[str] = mapped_column(String(32), ForeignKey("games.game_id"), primary_key=True)

    # Passing
    pass_completions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_yards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pass_tds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interceptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passer_rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rushing
    rush_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rush_yards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rush_tds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yards_per_carry: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Receiving
    receptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    targets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receiving_yards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receiving_tds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yards_per_reception: Mapped[float | None] = mapped_column(Float, nullable=True)

    # General
    fumbles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fumbles_lost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fantasy_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    snaps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Flexible storage for advanced metrics
    advanced_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Source tracking
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped[Player] = relationship(back_populates="game_stats")
    game: Mapped[Game] = relationship(back_populates="game_stats")


class PropLine(Base):
    __tablename__ = "prop_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"))
    game_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("games.game_id"), nullable=True)
    market: Mapped[str] = mapped_column(String(64))
    line_value: Mapped[float] = mapped_column(Float)
    over_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    under_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sportsbook: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consensus_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped[Player] = relationship(back_populates="prop_lines")
    game: Mapped[Game | None] = relationship(back_populates="prop_lines")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(32), ForeignKey("players.player_id"))
    game_id: Mapped[str] = mapped_column(String(32), ForeignKey("games.game_id"))
    predicted_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_props: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reasoning_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    player: Mapped[Player] = relationship(back_populates="predictions")
    game: Mapped[Game] = relationship(back_populates="predictions")


class DefenseProfile(Base):
    __tablename__ = "defense_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team: Mapped[str] = mapped_column(String(8))
    season: Mapped[int] = mapped_column(Integer)
    week_through: Mapped[int] = mapped_column(Integer)
    pass_yards_allowed: Mapped[float | None] = mapped_column(Float, nullable=True)
    rush_yards_allowed: Mapped[float | None] = mapped_column(Float, nullable=True)
    points_allowed: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_fantasy_points_allowed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pressure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage_grades: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("team", "season", "week_through", "source", name="uq_defense_profile"),
    )
