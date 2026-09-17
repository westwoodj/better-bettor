#!/usr/bin/env python
"""Run the Gridiron Oracle prediction pipeline for Super Bowl LX.

Seattle Seahawks vs New England Patriots -- February 8, 2026
Uses real 2025 season data pulled from ESPN's API.
"""

import logging
import os
import sys
import time

# Setup paths
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("super_bowl")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nfl_data_aggregator.db.sa_models import Base
from nfl_data_aggregator.db.repository import (
    PlayerRepo, GameRepo, StatsRepo, PropLineRepo, DefenseProfileRepo,
)
from nfl_data_aggregator.adapters.espn_api import NFLClient
from nfl_data_aggregator.pipeline.prediction_pipeline import PredictionPipeline

# --- Config -------------------------------------------------------------------

DB_PATH = os.path.join(ROOT, "gridiron_oracle_superbowl.db")
DB_URL = f"sqlite:///{DB_PATH}"
SEASON = 2025
SUPER_BOWL_GAME_ID = "sb_lx_2026"
HOME_TEAM = "SEA"   # Seahawks
AWAY_TEAM = "NE"    # Patriots
GOOGLE_API_KEY = os.environ.get("GOOGLE_GENAI_API_KEY")

# Key players to predict (name, team, position, ESPN ID)
# ESPN IDs verified against live ESPN roster API
KEY_PLAYERS = [
    # Seahawks offense
    ("Sam Darnold", "SEA", "QB", "3912547"),
    ("Kenneth Walker III", "SEA", "RB", "4567048"),
    ("Jaxon Smith-Njigba", "SEA", "WR", "4430878"),
    ("Cooper Kupp", "SEA", "WR", "2977187"),
    ("Rashid Shaheed", "SEA", "WR", "4032473"),
    ("AJ Barner", "SEA", "TE", "4576297"),

    # Patriots offense
    ("Drake Maye", "NE", "QB", "4431452"),
    ("Rhamondre Stevenson", "NE", "RB", "4569173"),
    ("Treveon Henderson", "NE", "RB", "4432710"),
    ("Kayshon Boutte", "NE", "WR", "4429022"),
    ("DeMario Douglas", "NE", "WR", "4427095"),
    ("Hunter Henry", "NE", "TE", "3046439"),
]

# ESPN gamelog stat name -> our DB column name
GAMELOG_STAT_MAP = {
    "completions": "pass_completions",
    "passingAttempts": "pass_attempts",
    "passingYards": "pass_yards",
    "passingTouchdowns": "pass_tds",
    "interceptions": "interceptions",
    "QBRating": "passer_rating",
    "rushingAttempts": "rush_attempts",
    "rushingYards": "rush_yards",
    "rushingTouchdowns": "rush_tds",
    "receptions": "receptions",
    "receivingTargets": "targets",
    "receivingYards": "receiving_yards",
    "receivingTouchdowns": "receiving_tds",
    "fumbles": "fumbles",
    "fumblesLost": "fumbles_lost",
}

# Prop lines for the Super Bowl
PROP_LINES = [
    # Sam Darnold
    ("3912547", "pass_yards", 265.5, -110, -110, "DraftKings"),
    ("3912547", "pass_tds", 1.5, -160, 130, "FanDuel"),
    ("3912547", "rush_yards", 12.5, -115, -105, "DraftKings"),
    # Kenneth Walker III
    ("4567048", "rush_yards", 72.5, -110, -110, "DraftKings"),
    ("4567048", "receptions", 2.5, -120, 100, "FanDuel"),
    # Jaxon Smith-Njigba
    ("4430878", "receiving_yards", 68.5, -110, -110, "DraftKings"),
    ("4430878", "receptions", 5.5, -115, -105, "FanDuel"),
    # Cooper Kupp
    ("2977187", "receiving_yards", 58.5, -110, -110, "DraftKings"),
    # Drake Maye
    ("4431452", "pass_yards", 224.5, -113, -111, "DraftKings"),
    ("4431452", "pass_tds", 1.5, 119, -153, "FanDuel"),
    ("4431452", "rush_yards", 35.5, -114, -110, "DraftKings"),
    ("4431452", "rush_attempts", 6.5, -125, -102, "DraftKings"),
    ("4431452", "completions", 20.5, 102, -130, "DraftKings"),
    ("4431452", "pass_attempts", 30.5, -118, -108, "DraftKings"),

    # Rhamondre Stevenson
    ("4569173", "rush_yards", 60.5, -110, -110, "DraftKings"),
    ("4569173", "rush_attempts", 14.5, 109, -139, "DraftKings"),
    ("4569173", "receptions", 3.5, 132, -168, "DraftKings"),
    ("4569173", "receiving_yards", 24.5, -112, -112, "DraftKings"),
    ("4432710", "rush_and_rec_yards", 76.5, -116, -110, "DraftKings"),

    # Hunter Henry
    ("3046439", "receiving_yards", 39.5, -109, -115, "DraftKings"),
    ("3046439", "receptions", 3.5, -135, 106, "FanDuel"),
    # Treveon Henderson
    ("4432710", "rush_yards", 19.5, -115, -109, "DraftKings"),
    ("4432710", "receptions", 0.5, -236, 182, "DraftKings"),
    ("4432710", "receiving_yards", 6.5, -103, -122, "DraftKings"),
    ("4432710", "rush_attempts", 5.5, 119, -152, "DraftKings"),
    ("4432710", "rush_and_rec_yards", 30.5, -108, -118, "DraftKings"),
]


def setup_database():
    """Create fresh DB and return session."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return Session()


def seed_players(session):
    """Insert key players into the DB."""
    repo = PlayerRepo(session)
    for name, team, pos, espn_id in KEY_PLAYERS:
        repo.upsert(
            espn_id,
            espn_id=espn_id,
            name=name,
            team=team,
            position=pos,
            status="active",
        )
    session.commit()
    logger.info("Seeded %d players", len(KEY_PLAYERS))


def seed_game(session):
    """Insert the Super Bowl game."""
    repo = GameRepo(session)
    repo.upsert(
        SUPER_BOWL_GAME_ID,
        season=SEASON,
        week=22,  # Super Bowl week
        game_type="SB",
        home_team=HOME_TEAM,
        away_team=AWAY_TEAM,
        venue="Caesars Superdome, New Orleans",
        weather_conditions={"temp": 72, "wind": 0, "dome": True},
    )
    session.commit()
    logger.info("Seeded Super Bowl game: %s vs %s", HOME_TEAM, AWAY_TEAM)


def _parse_gamelog_stats(names, stat_values):
    """Convert a gamelog stat row into a dict of DB column -> value."""
    result = {}
    for i, espn_name in enumerate(names):
        db_col = GAMELOG_STAT_MAP.get(espn_name)
        if db_col is None or i >= len(stat_values):
            continue
        raw = stat_values[i]
        if raw in (None, "-", "--", ""):
            continue
        try:
            if db_col in ("passer_rating",):
                result[db_col] = float(raw)
            else:
                result[db_col] = int(float(raw))
        except (ValueError, TypeError):
            continue
    return result


def fetch_and_seed_season_stats(session, espn_client):
    """Pull real 2025 season gamelogs from ESPN and seed into DB."""
    game_repo = GameRepo(session)
    stats_repo = StatsRepo(session)
    total_games = 0

    for name, team, pos, espn_id in KEY_PLAYERS:
        logger.info("Fetching gamelog for %s (%s)...", name, espn_id)
        try:
            data = espn_client.player_gamelog(espn_id, SEASON, force=True)
        except Exception as exc:
            logger.error("Failed to fetch gamelog for %s: %s", name, exc)
            continue

        stat_names = data.get("names", [])
        events_meta = data.get("events", {})

        # Process regular season + postseason
        for season_type in data.get("seasonTypes", []):
            st_name = season_type.get("displayName", "")
            is_post = "Post" in st_name
            game_type = "POST" if is_post else "REG"

            for cat in season_type.get("categories", []):
                for event in cat.get("events", []):
                    event_id = str(event.get("eventId", ""))
                    stat_values = event.get("stats", [])
                    if not event_id or not stat_values:
                        continue

                    # Get event metadata
                    meta = events_meta.get(event_id, {})
                    week = meta.get("week", 0)
                    opp = meta.get("opponent", {})
                    opp_abbr = opp.get("abbreviation", "UNK") if isinstance(opp, dict) else "UNK"
                    at_vs = meta.get("atVs", "vs")

                    # Determine home/away
                    if at_vs == "vs":
                        home, away = team, opp_abbr
                    else:
                        home, away = opp_abbr, team

                    # Upsert the game
                    game_id = f"{SEASON}_{week:02d}_{home}_{away}"
                    game_repo.upsert(
                        game_id,
                        season=SEASON,
                        week=week,
                        game_type=game_type,
                        home_team=home,
                        away_team=away,
                    )

                    # Parse stats
                    stats = _parse_gamelog_stats(stat_names, stat_values)
                    if stats:
                        stats_repo.upsert(
                            espn_id, game_id, source="espn", **stats,
                        )
                        total_games += 1

        time.sleep(0.5)  # rate limit courtesy

    session.commit()
    logger.info("Seeded %d real player-game stat rows from ESPN", total_games)


def seed_defense_profiles(session, espn_client):
    """Compute defense profiles by aggregating opponent stats from the DB.

    For each defensive team, find all regular season games and sum up the
    passing/rushing yards that opponent QBs/RBs/WRs put up against them.
    """
    from sqlalchemy import select
    from nfl_data_aggregator.db.sa_models import PlayerGameStats, Game, Player

    repo = DefenseProfileRepo(session)

    for def_team in (HOME_TEAM, AWAY_TEAM):
        # Find regular season games involving this team
        stmt = (
            select(Game)
            .where(Game.season == SEASON, Game.game_type == "REG")
            .where((Game.home_team == def_team) | (Game.away_team == def_team))
        )
        reg_games = list(session.execute(stmt).scalars().all())

        total_pass = 0
        total_rush = 0
        games_with_data = 0

        for game in reg_games:
            # Get stats for opponent players in this game
            opp_team = game.away_team if game.home_team == def_team else game.home_team

            stmt_stats = (
                select(PlayerGameStats)
                .join(Player)
                .where(
                    PlayerGameStats.game_id == game.game_id,
                    Player.team == opp_team,
                )
            )
            opp_stats = list(session.execute(stmt_stats).scalars().all())

            if opp_stats:
                games_with_data += 1
                for s in opp_stats:
                    total_pass += s.pass_yards or 0
                    total_rush += s.rush_yards or 0

        if games_with_data > 0:
            pass_yds_allowed = round(total_pass / games_with_data, 1)
            rush_yds_allowed = round(total_rush / games_with_data, 1)
        else:
            pass_yds_allowed = None
            rush_yds_allowed = None

        repo.upsert(
            team=def_team,
            season=SEASON,
            week_through=21,
            source="espn",
            pass_yards_allowed=pass_yds_allowed,
            rush_yards_allowed=rush_yds_allowed,
        )
        logger.info(
            "Defense profile for %s: pass_allowed=%.1f rush_allowed=%.1f (%d games)",
            def_team,
            pass_yds_allowed or 0,
            rush_yds_allowed or 0,
            games_with_data,
        )

    session.commit()


def seed_prop_lines(session):
    """Insert prop lines for key players."""
    repo = PropLineRepo(session)
    for espn_id, market, line, over, under, book in PROP_LINES:
        repo.add(
            player_id=espn_id,
            game_id=SUPER_BOWL_GAME_ID,
            market=market,
            line_value=line,
            over_odds=over,
            under_odds=under,
            sportsbook=book,
        )
    session.commit()
    logger.info("Seeded %d prop lines", len(PROP_LINES))


def configure_dspy():
    """Configure DSPy with Google Gemini."""
    import dspy
    lm = dspy.LM(
        model="gemini/gemini-3-pro-preview",
        api_key=GOOGLE_API_KEY,
        temperature=0.3,
    )
    dspy.configure(lm=lm)
    logger.info("DSPy configured with gemini/gemini-2.0-flash")
    return lm


def run_predictions(session, espn_client):
    """Run the prediction pipeline for each key player."""
    pipeline = PredictionPipeline(session, espn_client=espn_client)
    results = []

    # Predict for a subset of high-profile players
    predict_players = [
        ("Sam Darnold", "3912547"),
        ("Kenneth Walker III", "4567048"),
        ("Jaxon Smith-Njigba", "4430878"),
        ("Drake Maye", "4431452"),
        ("Rhamondre Stevenson", "4569173"),
        ("Treveon Henderson", "4432710"),
        ("Hunter Henry", "3046439"),
        ("Cooper Kupp", "2977187"),
        ("AJ Barner", "4576297"),
        ("Rashid Shaheed", "4032473")
    ]

    for name, espn_id in predict_players:
        logger.info("=" * 60)
        logger.info("Running prediction for %s...", name)
        try:
            result = pipeline.predict(espn_id, SUPER_BOWL_GAME_ID)
            results.append((name, result))
            logger.info("  Confidence: %.1f", result.confidence_score)
            logger.info("  Hallucination check: %s",
                        "PASSED" if result.hallucination_check and result.hallucination_check.passed else "ISSUES")
            # Rate limit courtesy -- Gemini free tier
            time.sleep(5)
        except Exception as e:
            logger.error("Failed for %s: %s", name, e)
            results.append((name, None))
            time.sleep(10)

    return results


def print_results(results):
    """Pretty print prediction results."""
    print("\n")
    print("=" * 80)
    print("  GRIDIRON ORACLE -- SUPER BOWL LX PREDICTIONS")
    print("  Seattle Seahawks vs New England Patriots")
    print("  February 8, 2026 -- Caesars Superdome, New Orleans")
    print("=" * 80)

    for name, result in results:
        print(f"\n{'-' * 70}")
        if result is None:
            print(f"  {name}: PREDICTION FAILED")
            continue

        qual = result.confidence_score
        grade = "A" if qual >= 80 else "B" if qual >= 65 else "C" if qual >= 50 else "D" if qual >= 35 else "F"

        print(f"  {name}")
        print(f"  Data Quality: {qual:.0f}/100 (Grade {grade})")

        if result.predicted_stats:
            print(f"\n  Predicted Stats:")
            for stat, pred in result.predicted_stats.items():
                if isinstance(pred, dict) and "expected" in pred:
                    floor = pred.get("floor", "?")
                    exp = pred["expected"]
                    ceil = pred.get("ceiling", "?")
                    print(f"    {stat:20s}: {exp:>6} (range: {floor} - {ceil})")

        if result.prop_comparisons:
            print(f"\n  Prop Recommendations:")
            for comp in result.prop_comparisons:
                edge = comp["edge"]
                arrow = ">> OVER " if edge > 0 else ">> UNDER"
                market = comp["market"]
                line = comp["line"]
                predicted = comp["predicted"]
                book = comp.get("sportsbook", "")
                print(f"    {arrow} {market:20s} {line:>6.1f}  (predicted: {predicted}, edge: {edge:+.1f})  [{book}]")

        if result.trend_analysis:
            print(f"\n  Analysis: {result.trend_analysis}")

        if result.risk_factors:
            print(f"  Risks: {result.risk_factors}")

        hc = result.hallucination_check
        if hc and not hc.passed:
            print(f"  *** HALLUCINATION WARNING: {len(hc.violations)} violation(s) ***")

    print(f"\n{'=' * 80}")
    print("  Data source: ESPN 2025 season gamelogs (regular season + postseason)")
    print("=" * 80)


def main():
    print("\nGridiron Oracle -- Super Bowl LX Pipeline")
    print("Initializing...\n")

    # 1. Setup
    session = setup_database()
    espn_client = NFLClient()
    logger.info("Database created: %s", DB_PATH)

    # 2. Seed data from ESPN
    seed_players(session)
    seed_game(session)
    fetch_and_seed_season_stats(session, espn_client)
    seed_defense_profiles(session, espn_client)
    seed_prop_lines(session)

    # 3. Configure LLM
    configure_dspy()

    # 4. Run predictions
    results = run_predictions(session, espn_client)

    # 5. Print results
    print_results(results)

    session.close()


if __name__ == "__main__":
    main()
