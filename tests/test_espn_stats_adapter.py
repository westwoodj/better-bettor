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


def test_score_uses_home_away_order_and_extracts_context():
    adapter = ESPNStatsAdapter()
    scoreboard = {
        "events": [{
            "id": "game1",
            "date": "2026-09-13T17:00:00Z",
            "season": {"year": 2026, "type": 2},
            "week": {"number": 1},
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "score": "17", "team": {"abbreviation": "BUF"}},
                    {"homeAway": "home", "score": "24", "team": {"abbreviation": "KC"}},
                ],
                "venue": {
                    "fullName": "Arrowhead Stadium",
                    "address": {"city": "Kansas City", "state": "MO"},
                },
                "weather": {"temperature": 72, "windSpeed": 8},
            }],
        }],
    }
    game = adapter.extract_games_from_scoreboard(scoreboard)[0]
    assert game["final_score"] == "24-17"
    assert game["venue_location"] == {"city": "Kansas City", "state": "MO"}
    assert game["weather_conditions"] == {"temp": 72, "wind": 8}


def test_extract_game_ids_from_nested_gamelog():
    adapter = ESPNStatsAdapter()
    gamelog = {
        "seasonTypes": [{"categories": [{"events": [
            {"id": "401000001"},
            {"event": {"$ref": "https://sports.core.api.espn.com/v2/events/401000002"}},
        ]}]}],
    }
    assert adapter.extract_game_ids_from_gamelog(gamelog) == ["401000001", "401000002"]


def test_roster_can_include_all_positions():
    adapter = ESPNStatsAdapter()
    roster = {"athletes": [{"items": [
        {"id": "1", "fullName": "QB", "position": {"abbreviation": "QB"}},
        {"id": "2", "fullName": "LB", "position": {"abbreviation": "LB"}},
    ]}]}
    assert len(adapter.extract_players_from_roster(roster, "KC")) == 1
    assert len(adapter.extract_players_from_roster(roster, "KC", include_all_positions=True)) == 2
