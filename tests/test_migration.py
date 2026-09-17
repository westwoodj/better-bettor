"""Migration coverage for databases created before venue_location existed."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_adds_venue_location_to_existing_sqlite_database(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE games (
            game_id VARCHAR(32) PRIMARY KEY,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            home_team VARCHAR(8) NOT NULL,
            away_team VARCHAR(8) NOT NULL
        )"""
    )
    connection.commit()
    connection.close()

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["PYTHONPATH"] = str(root / "src")
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    connection = sqlite3.connect(database)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(games)")}
    connection.close()
    assert "venue_location" in columns
