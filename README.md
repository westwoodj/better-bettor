# Gridiron Oracle

LLM-powered NFL player performance prediction engine with prop bet recommendations.

Gridiron Oracle combines DSPy structured reasoning with rigorous hallucination prevention and data quality confidence scoring to generate statistical projections for NFL players. It compares predictions against sportsbook prop lines to surface +EV betting opportunities.

## Quick Start

### Prerequisites

- Python 3.14+
- [pipenv](https://pipenv.pypa.io/)
- An Anthropic or OpenAI API key (for the DSPy prediction pipeline)

### Installation

```bash
git clone <repo-url>
cd better-bettor
pipenv install
```

### Environment Setup

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your configuration (see [Configuration](#configuration) below).

## Running the API

Start the FastAPI server:

```bash
pipenv run python -m nfl_data_aggregator.api.server
```

The server starts on `http://localhost:8000` by default. Interactive API docs (Swagger UI) are available at:

```
http://localhost:8000/docs
```

### Custom Host/Port

```bash
API_HOST=127.0.0.1 API_PORT=9000 pipenv run python -m nfl_data_aggregator.api.server
```

## API Endpoints

All endpoints are prefixed with `/v1`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/health` | System health check |
| `GET` | `/v1/teams/search?q=eagles` | Find team by name/abbreviation/city |
| `GET` | `/v1/teams/{team_abbr}/roster` | List skill-position players on a team |
| `GET` | `/v1/players/search?q=mahomes` | Search players by name (fuzzy match) |
| `GET` | `/v1/games/search?team=KC&season=2025&week=10` | Find games by team/season/week filters |
| `GET` | `/v1/players/{player_id}/prediction?game_id=X` | Single player prediction |
| `POST` | `/v1/predictions/batch` | Batch predictions |
| `GET` | `/v1/props/recommendations` | All prop recommendations |
| `GET` | `/v1/props/recommendations/{player_id}` | Player-specific props |
| `GET` | `/v1/players/{player_id}/stats` | Historical player stats |
| `GET` | `/v1/games/{game_id}/context` | Game context + defense profiles |

### Example Requests

**Health check:**
```bash
curl http://localhost:8000/v1/health
```

**Search teams:**
```bash
curl "http://localhost:8000/v1/teams/search?q=eagles"
```

**Team roster:**
```bash
curl http://localhost:8000/v1/teams/PHI/roster
```

**Search players:**
```bash
curl "http://localhost:8000/v1/players/search?q=mahomes"
curl "http://localhost:8000/v1/players/search?q=allen&team=BUF"
```

**Search games:**
```bash
curl "http://localhost:8000/v1/games/search?team=KC&season=2025&week=10"
curl "http://localhost:8000/v1/games/search?season=2025&week=1"
```

**Player stats:**
```bash
curl http://localhost:8000/v1/players/3912547/stats
```

**Game context:**
```bash
curl http://localhost:8000/v1/games/401234567/context
```

**Single prediction** (requires LLM API key):
```bash
curl "http://localhost:8000/v1/players/3912547/prediction?game_id=401234567"
```

**Batch predictions:**
```bash
curl -X POST http://localhost:8000/v1/predictions/batch \
  -H "Content-Type: application/json" \
  -d '{"predictions": [{"player_id": "3912547", "game_id": "401234567"}]}'
```

**Prop recommendations with filters:**
```bash
curl "http://localhost:8000/v1/props/recommendations?min_edge=3.0&sportsbook=DraftKings"
```

## Running the Pipeline Directly

You can run predictions without the API server using the CLI script:

```bash
pipenv run python scripts/run_super_bowl.py
```

This script ingests data from ESPN, runs the prediction pipeline for key players, and stores results in the SQLite database. After running it, the API endpoints for stats, context, and prop recommendations will return populated data.

To populate the DB-first roster endpoint with current skill-position players for all NFL teams:

```bash
python scripts/ingest_rosters.py --force
```

Use `--team-id 2` to ingest only one ESPN team (for example, Buffalo) and omit `--force` when a valid local roster cache should be reused.

## Configuration

All configuration is via environment variables (or a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///gridiron_oracle.db` | SQLAlchemy database URL |
| `DSPY_LM_PROVIDER` | `anthropic` | LLM provider (`anthropic` or `openai`) |
| `DSPY_MODEL` | `claude-sonnet-4-20250514` | Model identifier for DSPy |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DSPY_TEMPERATURE_ANALYSIS` | `0.3` | Temperature for player analysis stage |
| `DSPY_TEMPERATURE_PREDICTION` | `0.1` | Temperature for prediction generation |
| `NFL_SEASON` | `2025` | NFL season year |
| `ODDS_API_KEY` | — | The Odds API key |
| `SPORTS_DATA_API_KEY` | — | SportsData.IO API key |
| `GOOGLE_GENAI_API_KEY` | — | Google GenAI API key |
| `API_HOST` | `0.0.0.0` | API server bind host |
| `API_PORT` | `8000` | API server bind port |

## Running Tests

```bash
pipenv run python -m pytest tests/
```

With coverage:

```bash
pipenv run python -m pytest tests/ --cov=nfl_data_aggregator
```

## Architecture

The prediction pipeline runs in 7 stages:

1. **Context Assembly** (deterministic) — collects player profile, recent stats, matchup data, and prop lines from the database
2. **Data Quality Confidence** (deterministic) — scores the quality of available data on a 0-100 scale
3. **Player Analysis** (DSPy, temp=0.3) — LLM-driven trend, matchup, and risk analysis
4. **Prediction Generation** (DSPy, temp=0.1) — generates floor/expected/ceiling stat predictions
5. **Hallucination Check** (deterministic) — verifies all LLM claims against source data via regex
6. **Prop Comparison** (deterministic) — compares predictions against sportsbook lines to find edges
7. **Persistence** — saves prediction, confidence scores, and recommendations to the database

For the full system design, see [`.claude/gridiron-oracle-architecture.md`](.claude/gridiron-oracle-architecture.md).

## Security

Do not commit API keys. Use environment variables or a `.env` file (which is gitignored).
