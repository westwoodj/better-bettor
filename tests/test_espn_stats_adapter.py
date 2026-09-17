"""Tests for ESPN stats adapter using fixture data."""

import os, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from nfl_data_aggregator.adapters.espn_stats_adapter import ESPNStatsAdapter


def test_extract_games_from_scoreboard():
    adapter = ESPNStatsAdapter()
    scoreboard = {
        "events": [
            {
                "id": "401234567",
                "date": "2025-11-02T20:00Z",
                "season": {"year": 2025, "type": 2},
                "week": {"number": 9},
                "competitions": [{
                    "competitors": [
                        {"team": {"abbreviation": "KC"}, "homeAway": "home", "score": "31"},
                        {"team": {"abbreviation": "BUF"}, "homeAway": "away", "score": "24"},
                    ],
                    "venue": {"fullName": "Arrowhead Stadium"},
                }],
            }
        ]
    }

    games = adapter.extract_games_from_scoreboard(scoreboard)
    assert len(games) == 1
    assert games[0]["game_id"] == "401234567"
    assert games[0]["home_team"] == "KC"
    assert games[0]["away_team"] == "BUF"
    assert games[0]["final_score"] == "31-24"


def test_extract_stats_from_event_summary():
    adapter = ESPNStatsAdapter()
    summary = {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "KC"},
                    "statistics": [
                        {
                            "name": "passing",
                            "labels": ["C/ATT", "YDS", "TD", "INT"],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "12345",
                                        "displayName": "Patrick Mahomes",
                                        "position": {"abbreviation": "QB"},
                                    },
                                    "stats": ["25/35", "310", "3", "1"],
                                }
                            ],
                        },
                        {
                            "name": "rushing",
                            "labels": ["CAR", "YDS", "TD"],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "12345",
                                        "displayName": "Patrick Mahomes",
                                        "position": {"abbreviation": "QB"},
                                    },
                                    "stats": ["5", "28", "0"],
                                }
                            ],
                        },
                    ],
                }
            ]
        }
    }

    stats = adapter.extract_stats_from_event_summary(summary, "game1")
    assert len(stats) == 1  # Merged into one entry
    assert stats[0]["player_id"] == "12345"
    assert stats[0]["pass_completions"] == 25
    assert stats[0]["pass_attempts"] == 35
    assert stats[0]["pass_yards"] == 310.0
    assert stats[0]["pass_tds"] == 3.0
    assert stats[0]["rush_yards"] == 28.0


def test_extract_player_info_from_summary():
    adapter = ESPNStatsAdapter()
    summary = {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "KC"},
                    "statistics": [
                        {
                            "name": "passing",
                            "labels": [],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "12345",
                                        "displayName": "Patrick Mahomes",
                                        "position": {"abbreviation": "QB"},
                                    },
                                    "stats": [],
                                }
                            ],
                        },
                        {
                            "name": "rushing",
                            "labels": [],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "67890",
                                        "displayName": "Isiah Pacheco",
                                        "position": {"abbreviation": "RB"},
                                    },
                                    "stats": [],
                                },
                                {
                                    "athlete": {
                                        "id": "12345",
                                        "displayName": "Patrick Mahomes",
                                        "position": {"abbreviation": "QB"},
                                    },
                                    "stats": [],
                                },
                            ],
                        },
                    ],
                }
            ]
        }
    }

    players = adapter.extract_player_info_from_summary(summary)
    assert len(players) == 2  # Deduped
    ids = {p["player_id"] for p in players}
    assert "12345" in ids
    assert "67890" in ids


def test_filters_non_skill_positions():
    adapter = ESPNStatsAdapter()
    summary = {
        "boxscore": {
            "players": [
                {
                    "team": {"abbreviation": "KC"},
                    "statistics": [
                        {
                            "name": "defensive",
                            "labels": [],
                            "athletes": [
                                {
                                    "athlete": {
                                        "id": "99999",
                                        "displayName": "Chris Jones",
                                        "position": {"abbreviation": "DT"},
                                    },
                                    "stats": [],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }

    players = adapter.extract_player_info_from_summary(summary)
    assert len(players) == 0
