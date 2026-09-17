"""Dataclasses for the prediction pipeline context.

These are pure data containers bridging DB models and the DSPy pipeline.
All formatting methods produce structured text for LLM consumption.
"""

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class PlayerProfile:
    player_id: str
    name: str
    team: str = ""
    position: str = ""
    status: str = "active"
    height: str = ""
    weight: int | None = None
    experience: int | None = None


@dataclass
class GameStats:
    game_id: str
    week: int
    season: int
    opponent: str = ""
    pass_completions: int | None = None
    pass_attempts: int | None = None
    pass_yards: int | None = None
    pass_tds: int | None = None
    interceptions: int | None = None
    passer_rating: float | None = None
    rush_attempts: int | None = None
    rush_yards: int | None = None
    rush_tds: int | None = None
    receptions: int | None = None
    targets: int | None = None
    receiving_yards: int | None = None
    receiving_tds: int | None = None
    fumbles: int | None = None
    fantasy_points: float | None = None
    source: str = ""


@dataclass
class SeasonAverages:
    games_played: int = 0
    avg_pass_yards: float = 0.0
    avg_pass_tds: float = 0.0
    avg_rush_yards: float = 0.0
    avg_rush_tds: float = 0.0
    avg_receptions: float = 0.0
    avg_receiving_yards: float = 0.0
    avg_receiving_tds: float = 0.0
    avg_fantasy_points: float = 0.0
    total_pass_yards: int = 0
    total_rush_yards: int = 0
    total_receiving_yards: int = 0


@dataclass
class MatchupContext:
    game_id: str
    opponent: str = ""
    home_away: str = ""
    opponent_pass_yards_allowed: float | None = None
    opponent_rush_yards_allowed: float | None = None
    opponent_points_allowed: float | None = None
    opponent_pressure_rate: float | None = None


@dataclass
class GameEnvironment:
    venue: str = ""
    weather_temp: float | None = None
    weather_wind: float | None = None
    game_type: str = "regular"


@dataclass
class PropLineContext:
    market: str
    line_value: float
    over_odds: float | None = None
    under_odds: float | None = None
    sportsbook: str = ""


@dataclass
class PredictionContext:
    player: PlayerProfile
    recent_games: list[GameStats] = field(default_factory=list)
    season_averages: SeasonAverages = field(default_factory=SeasonAverages)
    matchup: MatchupContext | None = None
    environment: GameEnvironment = field(default_factory=GameEnvironment)
    prop_lines: list[PropLineContext] = field(default_factory=list)
    roster_verified: bool = False
    roster_warnings: list[str] = field(default_factory=list)

    def format_player_section(self) -> str:
        p = self.player
        lines = [
            f"Player: {p.name}",
            f"Position: {p.position}",
            f"Team: {p.team}",
            f"Status: {p.status}",
        ]
        if p.experience is not None:
            lines.append(f"Experience: {p.experience} years")
        return "\n".join(lines)

    def format_recent_games(self) -> str:
        if not self.recent_games:
            return "No recent game data available."
        lines = ["Recent Games:"]
        for g in self.recent_games:
            parts = [f"  Week {g.week} vs {g.opponent}:"]
            if g.pass_yards is not None:
                parts.append(f"    Passing: {g.pass_completions or 0}/{g.pass_attempts or 0} for {g.pass_yards} yds, {g.pass_tds or 0} TD, {g.interceptions or 0} INT")
            if g.rush_yards is not None:
                parts.append(f"    Rushing: {g.rush_attempts or 0} att, {g.rush_yards} yds, {g.rush_tds or 0} TD")
            if g.receiving_yards is not None:
                parts.append(f"    Receiving: {g.receptions or 0} rec ({g.targets or 0} tgt), {g.receiving_yards} yds, {g.receiving_tds or 0} TD")
            if g.fantasy_points is not None:
                parts.append(f"    Fantasy: {g.fantasy_points:.1f} pts")
            lines.extend(parts)
        return "\n".join(lines)

    def format_matchup_section(self) -> str:
        if self.matchup is None:
            return "No matchup data available."
        m = self.matchup
        lines = [
            f"Matchup: vs {m.opponent} ({m.home_away})",
        ]
        if m.opponent_pass_yards_allowed is not None:
            lines.append(f"  Opponent pass yards allowed/game: {m.opponent_pass_yards_allowed:.1f}")
        if m.opponent_rush_yards_allowed is not None:
            lines.append(f"  Opponent rush yards allowed/game: {m.opponent_rush_yards_allowed:.1f}")
        if m.opponent_points_allowed is not None:
            lines.append(f"  Opponent points allowed/game: {m.opponent_points_allowed:.1f}")
        if m.opponent_pressure_rate is not None:
            lines.append(f"  Opponent pressure rate: {m.opponent_pressure_rate:.1%}")
        return "\n".join(lines)

    def format_environment_section(self) -> str:
        e = self.environment
        lines = []
        if e.venue:
            lines.append(f"Venue: {e.venue}")
        if e.weather_temp is not None:
            lines.append(f"Temperature: {e.weather_temp}°F")
        if e.weather_wind is not None:
            lines.append(f"Wind: {e.weather_wind} mph")
        if e.game_type != "regular":
            lines.append(f"Game type: {e.game_type}")
        return "\n".join(lines) if lines else "No environment data available."

    def format_baselines(self) -> str:
        a = self.season_averages
        if a.games_played == 0:
            return "No season baseline data available."
        lines = [
            f"Season Averages ({a.games_played} games):",
            f"  Passing: {a.avg_pass_yards:.1f} yds/game, {a.avg_pass_tds:.1f} TD/game",
            f"  Rushing: {a.avg_rush_yards:.1f} yds/game, {a.avg_rush_tds:.1f} TD/game",
            f"  Receiving: {a.avg_receptions:.1f} rec/game, {a.avg_receiving_yards:.1f} yds/game, {a.avg_receiving_tds:.1f} TD/game",
            f"  Fantasy: {a.avg_fantasy_points:.1f} pts/game",
        ]
        return "\n".join(lines)

    def format_prop_lines(self) -> str:
        if not self.prop_lines:
            return "No prop lines available."
        lines = ["Current Prop Lines:"]
        for p in self.prop_lines:
            odds_str = ""
            if p.over_odds is not None and p.under_odds is not None:
                odds_str = f" (O {p.over_odds:+.0f} / U {p.under_odds:+.0f})"
            lines.append(f"  {p.market}: {p.line_value}{odds_str} [{p.sportsbook}]")
        return "\n".join(lines)

    def compute_snapshot_hash(self) -> str:
        """Compute a hash of the data snapshot for reproducibility tracking."""
        data = {
            "player_id": self.player.player_id,
            "games_played": self.season_averages.games_played,
            "recent_games": len(self.recent_games),
            "has_matchup": self.matchup is not None,
            "prop_lines": len(self.prop_lines),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
