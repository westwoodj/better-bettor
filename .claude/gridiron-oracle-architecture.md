# Gridiron Oracle — System Architecture

## NFL Player Performance Prediction & Prop Bet Recommendation Engine

---

## 1. System Overview

Gridiron Oracle is an LLM-powered system that predicts individual NFL player performances and recommends player prop bets by comparing model-generated projections against consensus sportsbook lines. The system emphasizes **verified data grounding**, **structured LLM reasoning via DSPy**, and **rigorous hallucination prevention**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT / CONSUMER                            │
│                 (Web App, Mobile, Discord Bot)                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  REST / GraphQL
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         API GATEWAY                                 │
│             (Auth, Rate Limiting, Request Validation)               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
   │ Prediction  │ │   Lines &   │ │   Player /   │
   │  Service    │ │  Odds Svc   │ │  Game Data   │
   │  (DSPy)     │ │             │ │   Service    │
   └──────┬──────┘ └──────┬──────┘ └──────┬───────┘
          │               │               │
          ▼               ▼               ▼
   ┌─────────────────────────────────────────────┐
   │           VERIFIED DATA LAYER               │
   │  (PostgreSQL + Vector Store + Cache)        │
   └──────────────────┬──────────────────────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
   ┌───────────┐ ┌─────────┐ ┌─────────────┐
   │  ESPN API │ │ PFF API │ │ Odds APIs   │
   │ / nflverse│ │         │ │ (The Odds   │
   │           │ │         │ │  API, etc.) │
   └───────────┘ └─────────┘ └─────────────┘
```

---

## 2. Core Components

### 2.1 API Gateway

**Technology:** FastAPI (Python) — chosen for native async, Pydantic validation, and tight Python ecosystem integration with DSPy.

**Responsibilities:**
- Authentication (API keys initially; JWT/OAuth2 for future consumer apps)
- Rate limiting per client tier
- Request validation and schema enforcement
- Response caching (Redis) for identical queries within a configurable TTL
- Request tracing (correlation IDs for debugging the full LLM pipeline)

**Key Endpoints (MVP):**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/players/{player_id}/prediction` | Single player performance prediction |
| `POST` | `/v1/predictions/batch` | Batch predictions for a slate (e.g., Sunday Week 8) |
| `GET` | `/v1/props/recommendations` | Recommended prop bets (filtered by sport, week, confidence) |
| `GET` | `/v1/props/recommendations/{player_id}` | Props for a specific player |
| `GET` | `/v1/players/{player_id}/stats` | Verified historical stats (passthrough to data layer) |
| `GET` | `/v1/games/{game_id}/context` | Game context (matchup, weather, injuries) |
| `GET` | `/v1/health` | System health + model readiness |

### 2.2 Verified Data Layer

This is the **single source of truth** the LLM is allowed to reason over. The LLM never generates statistics from its parametric memory — all factual claims must be traceable to records in this layer.

#### 2.2.1 Data Sources (MVP)

| Source | Data Provided | Access Method |
|--------|--------------|---------------|
| **ESPN API** | Scores, schedules, rosters, basic box scores | Public REST endpoints |
| **nflverse / nflfastR** | Play-by-play, advanced stats (EPA, CPOE, etc.) | R data packages → ETL to Postgres |
| **PFF** (if licensed) | Player grades, pass-rush win rates, coverage stats | Commercial API |
| **The Odds API** | Consensus lines, player props from major books | REST API (free tier available) |
| **Weather API** | Game-day conditions (wind, temp, precipitation) | OpenWeatherMap or similar |
| **Injury Reports** | Official NFL injury designations | ESPN or NFL.com scraping + manual verification |

#### 2.2.2 Database Schema (PostgreSQL)

```
── players
│   ├── player_id (PK)
│   ├── name, team, position, status
│   ├── height, weight, experience
│   └── updated_at
│
── games
│   ├── game_id (PK)
│   ├── season, week, game_type
│   ├── home_team, away_team
│   ├── kickoff_time, venue
│   ├── weather_conditions (JSONB)
│   └── final_score (nullable)
│
── player_game_stats
│   ├── player_id (FK) + game_id (FK) (composite PK)
│   ├── passing_yards, passing_tds, interceptions
│   ├── rushing_yards, rushing_tds, carries
│   ├── receiving_yards, receiving_tds, receptions, targets
│   ├── fantasy_points_ppr
│   ├── snap_count, snap_percentage
│   ├── advanced_stats (JSONB — EPA, CPOE, YAC, ADOT, etc.)
│   └── source + source_timestamp (data provenance)
│
── prop_lines
│   ├── line_id (PK)
│   ├── player_id (FK), game_id (FK)
│   ├── market (e.g., "passing_yards", "anytime_td")
│   ├── line_value, over_odds, under_odds
│   ├── sportsbook
│   ├── consensus_line (computed)
│   └── retrieved_at
│
── predictions  (output table — audit trail)
│   ├── prediction_id (PK)
│   ├── player_id (FK), game_id (FK)
│   ├── predicted_stats (JSONB)
│   ├── confidence_score, confidence_breakdown (JSONB)
│   ├── recommended_props (JSONB)
│   ├── reasoning_trace (TEXT — full chain-of-thought)
│   ├── data_snapshot_hash (links to exact data used)
│   ├── model_version
│   └── created_at
│
── defense_profiles
│   ├── team, season, week_through
│   ├── pass_yards_allowed_per_game, rush_yards_allowed_per_game
│   ├── position_fantasy_points_allowed (JSONB — by position)
│   ├── pressure_rate, coverage_grades (JSONB)
│   └── source
```

#### 2.2.3 Data Ingestion Pipeline

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scheduled   │────▶│   Extract    │────▶│  Validate &  │
│  Triggers    │     │  (API calls) │     │  Normalize   │
│  (cron/      │     │              │     │              │
│   Airflow)   │     └──────────────┘     └──────┬───────┘
└──────────────┘                                  │
                                                  ▼
                                          ┌──────────────┐
                                          │   Load to    │
                                          │  PostgreSQL  │
                                          │  + tag with  │
                                          │  provenance  │
                                          └──────────────┘
```

**Ingestion Cadence:**
- **Weekly (Tuesday):** Full stat updates for completed games
- **Daily (during season):** Injury reports, line movements, roster changes
- **Pre-game (2 hours before kickoff):** Final injury statuses, weather, line snapshots
- **Post-game:** Results for prediction accuracy tracking

**Validation Rules:**
- Cross-reference stats across sources (ESPN vs. nflverse) — flag discrepancies > 5%
- Reject records missing required fields
- Every record tagged with `source`, `source_timestamp`, `ingested_at`

---

## 3. LLM Prediction Pipeline (DSPy)

### 3.1 Why DSPy

DSPy is chosen over raw prompt engineering because:

1. **Prompt optimization:** DSPy's optimizers (BootstrapFewShot, MIPROv2) automatically tune prompts and few-shot examples against a metric — critical when prediction accuracy is measurable.
2. **Modular pipeline composition:** Each reasoning step is a separate DSPy `Module`, making the system testable, debuggable, and swappable.
3. **Reproducibility:** Compiled programs are serializable, versioned, and deterministic for a given input.
4. **Weight optimization path:** DSPy supports fine-tuning-as-compilation, allowing future migration from prompt-tuning to actual weight updates when enough prediction data accumulates.

### 3.2 Pipeline Architecture

The prediction pipeline is a **multi-stage DSPy program** where each stage has a clearly defined input/output contract, and the LLM is never exposed to unstructured or unverified data.

```
┌────────────────────────────────────────────────────────────────────┐
│                    DSPy Prediction Pipeline                        │
│                                                                    │
│  ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌──────────────┐  │
│  │  Stage 1 │──▶│  Stage 2 │──▶│  Stage 3  │──▶│   Stage 4    │  │
│  │  Context │   │  Player  │   │ Prediction│   │  Prop Bet    │  │
│  │ Assembly │   │ Analysis │   │ Generation│   │ Recommender  │  │
│  └──────────┘   └──────────┘   └───────────┘   └──────────────┘  │
│       │              │              │                  │           │
│       ▼              ▼              ▼                  ▼           │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │              Confidence Scoring Module                        │ │
│  │         (runs in parallel with Stage 3 & 4)                  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│       │              │              │                  │           │
│       ▼              ▼              ▼                  ▼           │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │           Hallucination Verification Gate                    │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

### 3.3 Stage Definitions

#### Stage 1: Context Assembly (Non-LLM)

This is a **deterministic data retrieval step** — no LLM involved. It constructs the structured context window that all subsequent stages will reason over.

```python
class ContextAssembler:
    """Gathers and formats all verified data for a prediction request."""

    def forward(self, player_id: str, game_id: str) -> PredictionContext:
        return PredictionContext(
            player_profile=self.get_player_profile(player_id),
            recent_games=self.get_last_n_games(player_id, n=8),
            season_averages=self.get_season_averages(player_id),
            matchup_context=self.get_defense_profile(game_id, player_id),
            game_environment=self.get_game_environment(game_id),  # weather, H/A, dome
            injury_status=self.get_injury_report(player_id),
            historical_vs_opponent=self.get_h2h_history(player_id, game_id),
            team_context=self.get_team_context(player_id),  # pace, pass/run ratio
            prop_lines=self.get_current_lines(player_id, game_id),
        )
```

**Context Window Management:** Each data element is serialized into a structured text block with clear section headers and explicit data provenance tags. A token budget is enforced:

| Section | Max Tokens | Priority |
|---------|-----------|----------|
| Player recent games (8 games) | 2,000 | Critical |
| Season averages | 300 | Critical |
| Matchup/defense profile | 800 | Critical |
| Game environment | 200 | High |
| Injury report | 200 | High |
| Historical vs. opponent | 500 | Medium |
| Team context | 400 | Medium |
| Prop lines | 300 | High |
| **Total budget** | **~4,700** | — |

If token budget is exceeded, lower-priority sections are truncated with a note: `[TRUNCATED — full data available in database, not included due to context limits]`.

#### Stage 2: Player Analysis (DSPy Module)

```python
class PlayerAnalysis(dspy.Module):
    """Analyzes trends, matchup advantages/disadvantages, and situational factors."""

    def __init__(self):
        self.analyze = dspy.ChainOfThought(
            "player_context, matchup_context, game_environment -> "
            "trend_analysis, matchup_assessment, key_factors, risk_factors"
        )

    def forward(self, context: PredictionContext):
        return self.analyze(
            player_context=context.format_player_section(),
            matchup_context=context.format_matchup_section(),
            game_environment=context.format_environment_section(),
        )
```

**Key design decisions:**
- Uses `ChainOfThought` to force explicit intermediate reasoning.
- Output fields are structured — `trend_analysis` and `matchup_assessment` are constrained to reference only data present in the input context.

#### Stage 3: Prediction Generation (DSPy Module)

```python
class PredictionGenerator(dspy.Module):
    """Generates specific stat predictions with ranges."""

    def __init__(self):
        self.predict = dspy.ChainOfThought(
            "player_analysis, player_context, historical_baselines -> "
            "predicted_stats, prediction_ranges, reasoning"
        )

    def forward(self, analysis, context: PredictionContext):
        return self.predict(
            player_analysis=analysis,
            player_context=context.format_player_section(),
            historical_baselines=context.format_baselines(),
        )
```

**Output schema for `predicted_stats`:**
```json
{
  "passing_yards": { "prediction": 274, "floor": 220, "ceiling": 340 },
  "passing_tds": { "prediction": 2.1, "floor": 1, "ceiling": 3 },
  "interceptions": { "prediction": 0.7, "floor": 0, "ceiling": 2 },
  "rushing_yards": { "prediction": 18, "floor": 5, "ceiling": 35 }
}
```

#### Stage 4: Prop Bet Recommender (DSPy Module)

```python
class PropRecommender(dspy.Module):
    """Compares predictions against consensus lines to find edges."""

    def __init__(self):
        self.recommend = dspy.ChainOfThought(
            "predicted_stats, prediction_ranges, prop_lines, confidence_score -> "
            "recommendations, edge_analysis"
        )

    def forward(self, predictions, confidence, context: PredictionContext):
        return self.recommend(
            predicted_stats=predictions.predicted_stats,
            prediction_ranges=predictions.prediction_ranges,
            prop_lines=context.format_prop_lines(),
            confidence_score=confidence,
        )
```

**Recommendation output:**
```json
{
  "recommendations": [
    {
      "player": "Patrick Mahomes",
      "market": "passing_yards",
      "line": 275.5,
      "direction": "OVER",
      "predicted_value": 298,
      "edge_pct": 8.2,
      "confidence": 72,
      "reasoning": "...",
      "risk_flags": ["divisional_road_game"]
    }
  ]
}
```

### 3.4 DSPy Optimization Strategy

#### Training Data
- Historical predictions can be scored against actual outcomes, creating a growing labeled dataset.
- Initial bootstrapping uses expert-curated examples (10–20 hand-labeled prediction chains per position).

#### Optimization Loop
```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Collect     │────▶│  Run DSPy    │────▶│  Deploy best   │
│  game        │     │  Optimizer   │     │  compiled      │
│  outcomes    │     │  (weekly)    │     │  program       │
│  + score     │     │              │     │                │
│  predictions │     │  Metric:     │     └────────────────┘
│              │     │  prediction  │
└─────────────┘     │  accuracy    │
                    └──────────────┘
```

**Metric function:**
```python
def prediction_accuracy(example, prediction, trace=None):
    """Composite score: stat accuracy + prop bet hit rate."""
    stat_score = mean_absolute_percentage_error(
        example.actual_stats, prediction.predicted_stats
    )
    prop_score = prop_bet_accuracy(
        example.actual_stats, prediction.recommendations
    )
    # Penalize low-confidence correct predictions less than
    # high-confidence wrong predictions
    confidence_calibration = calibration_penalty(
        prediction.confidence_score, prop_score
    )
    return weighted_average(stat_score, prop_score, confidence_calibration)
```

**Optimizer choice:**
- **Bootstrap phase** (< 50 labeled examples): `BootstrapFewShot`
- **Growth phase** (50–500 examples): `MIPROv2`
- **Mature phase** (500+ examples): Evaluate `BootstrapFinetune` for weight optimization on a smaller model (e.g., fine-tuned Llama) to reduce cost

---

## 4. Confidence Scoring System

The confidence score is a **composite, non-arbitrary metric** built from multiple measurable signals. It is NOT generated by asking the LLM "how confident are you?" — that approach produces uncalibrated scores.

### 4.1 Confidence Components

```
┌─────────────────────────────────────────────────────────┐
│              COMPOSITE CONFIDENCE SCORE (0-100)          │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │   Data       │  │  Prediction  │  │   Model       │ │
│  │   Quality    │  │  Stability   │  │   Calibration │ │
│  │   (0-100)    │  │  (0-100)     │  │   (0-100)     │ │
│  │   Weight: 25%│  │  Weight: 35% │  │   Weight: 40% │ │
│  └──────────────┘  └──────────────┘  └───────────────┘ │
└─────────────────────────────────────────────────────────┘
```

#### Component 1: Data Quality Score (25%)
Computed deterministically — no LLM involved.

| Signal | Measurement | Impact |
|--------|------------|--------|
| Games played this season | < 4 games = penalty | -20 if < 4 |
| Data source agreement | ESPN vs. nflverse stat diff | -15 if > 5% diff |
| Injury ambiguity | Questionable/Doubtful = penalty | -10 to -30 |
| Missing data fields | % of schema fields populated | Proportional |
| Opponent data freshness | Days since last defensive update | -5 per stale day |

#### Component 2: Prediction Stability Score (35%)
Measures consistency across multiple inference runs.

```python
def stability_score(player_id, game_id, n_runs=5):
    """Run prediction N times with temperature > 0 and measure variance."""
    predictions = [run_prediction(player_id, game_id) for _ in range(n_runs)]
    stat_variances = compute_per_stat_variance(predictions)
    direction_agreement = compute_recommendation_agreement(predictions)

    # High variance = low confidence
    stability = 100 - normalize(mean(stat_variances))
    # If 5/5 runs say "OVER 275.5" → high; if 3/5 → lower
    consistency_bonus = direction_agreement * 20

    return min(100, stability + consistency_bonus)
```

#### Component 3: Model Calibration Score (40%)
Based on **historical accuracy** for similar prediction contexts.

```python
def calibration_score(player_id, context_features):
    """How well has the model performed on similar predictions historically?"""
    similar_past = find_similar_predictions(
        position=context_features.position,
        spread_range=context_features.spread_range,
        home_away=context_features.home_away,
        matchup_tier=context_features.defense_tier,
    )
    if len(similar_past) < 10:
        return 50  # Insufficient history — neutral score

    historical_accuracy = compute_accuracy(similar_past)
    return scale_to_100(historical_accuracy)
```

### 4.2 Confidence Thresholds for Recommendations

| Score Range | Label | Recommendation Policy |
|------------|-------|----------------------|
| 80–100 | High Confidence | Strong recommendation — highlight to user |
| 60–79 | Moderate Confidence | Standard recommendation with caveats |
| 40–59 | Low Confidence | Include but flag uncertainty prominently |
| 0–39 | Insufficient | Do not recommend — show prediction only with disclaimer |

---

## 5. Hallucination Prevention & Accuracy Safeguards

This is the most critical section. LLMs will confidently fabricate statistics if not constrained.

### 5.1 Architecture-Level Safeguards

#### 5.1.1 Data Firewall

The LLM **never** retrieves data on its own. All data flows through the Context Assembly stage (Stage 1), which is entirely deterministic code.

```
 ❌ LLM → "Mahomes averaged 285 yards last 5 games" (from parametric memory)
 ✅ LLM → Reasons over explicitly provided table of last 5 games
```

**Enforcement:** The DSPy system prompt includes:
```
You are a sports analyst. You MUST ONLY reference statistics and facts 
that appear in the PROVIDED DATA sections below. If data for a specific 
stat is not provided, state "data not available" — do not estimate or 
recall from memory. Every statistical claim you make must be verifiable 
against the provided data.
```

#### 5.1.2 Hallucination Verification Gate

A **separate DSPy module** that runs after prediction generation and acts as a fact-checker.

```python
class HallucinationChecker(dspy.Module):
    """Verifies all factual claims in the prediction against source data."""

    def __init__(self):
        self.verify = dspy.ChainOfThought(
            "prediction_output, source_data -> "
            "verified_claims, flagged_claims, hallucination_detected"
        )

    def forward(self, prediction_output, source_data):
        result = self.verify(
            prediction_output=prediction_output,
            source_data=source_data,
        )
        if result.hallucination_detected:
            return self.remediate(result, source_data)
        return result
```

**Additionally, a deterministic checker runs in parallel:**

```python
def deterministic_fact_check(prediction_text: str, source_data: dict) -> list:
    """Extract all numeric claims from prediction and verify against source."""
    claims = extract_numeric_claims(prediction_text)  # regex + NER
    violations = []
    for claim in claims:
        if not verify_against_source(claim, source_data):
            violations.append(claim)
    return violations
```

If **any** violation is found, the prediction is regenerated with the violations flagged in the prompt, or rejected entirely if it fails 3 attempts.

#### 5.1.3 Structured Output Enforcement

All LLM outputs are parsed into Pydantic models. If the LLM produces output that doesn't conform to the expected schema, the call is retried with a correction prompt.

```python
class PlayerPrediction(BaseModel):
    player_id: str
    game_id: str
    predicted_stats: dict[str, StatPrediction]
    reasoning: str
    data_references: list[str]  # Must cite specific data points used
    risk_factors: list[str]

class StatPrediction(BaseModel):
    prediction: float
    floor: float
    ceiling: float

    @validator('prediction')
    def prediction_within_range(cls, v, values):
        # Sanity bounds — e.g., no QB throws for 900 yards
        assert 0 <= v <= 800, "Prediction outside plausible range"
        return v
```

### 5.2 Context Overload Prevention

| Strategy | Implementation |
|----------|---------------|
| **Token budgeting** | Hard caps per context section (see §3.3 Stage 1) |
| **Relevance filtering** | Only include stats relevant to the prediction market (don't load rushing stats when predicting a WR's receiving yards) |
| **Summarization for history** | Games older than 4 weeks are summarized into aggregate stats rather than game-by-game |
| **Chunked reasoning** | The multi-stage pipeline naturally chunks reasoning — no single LLM call processes all data at once |

### 5.3 Consistency Safeguards

| Strategy | Implementation |
|----------|---------------|
| **Multi-run voting** | Key predictions are run 3–5 times; outliers are discarded (see §4.1 Stability Score) |
| **Temperature control** | Stage 2 (analysis) uses temp 0.3–0.5; Stage 3 (prediction) uses temp 0.1–0.2 for consistency |
| **Compiled programs** | DSPy compiles optimized prompts — no drift from manual prompt editing |
| **Version pinning** | Every prediction records the exact model version + compiled program version |
| **Regression testing** | Weekly automated evaluation against a held-out test set of historical games |

---

## 6. Tech Stack Summary

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **API** | FastAPI | Async, Pydantic-native, OpenAPI docs |
| **LLM Framework** | DSPy | Prompt optimization, modular pipelines |
| **LLM Provider** | Anthropic (Claude) or OpenAI | Start with strongest model; migrate to fine-tuned smaller model later |
| **Database** | PostgreSQL | Relational integrity for stats; JSONB for flexible advanced stats |
| **Vector Store** | pgvector (extension) | Similarity search for historical comparisons (same DB, simpler ops) |
| **Cache** | Redis | API response caching, rate limiting, prediction dedup |
| **Task Queue** | Celery + Redis | Async batch predictions, data ingestion jobs |
| **ETL / Scheduling** | Airflow (or Prefect) | Data pipeline orchestration |
| **Monitoring** | Prometheus + Grafana | API metrics, prediction accuracy tracking |
| **LLM Observability** | LangSmith or Arize Phoenix | Trace LLM calls, monitor prompt performance, track costs |
| **Infrastructure** | Docker + Kubernetes (or Railway/Fly.io for MVP) | Containerized, scalable |

---

## 7. MVP Scoping & Phased Rollout

### Phase 1 — MVP (Weeks 1–6)
- [ ] Data pipeline: ESPN + nflverse → PostgreSQL (skill positions: QB, RB, WR, TE)
- [ ] Context assembly for single-player predictions
- [ ] 2-stage DSPy pipeline (Analysis → Prediction) with basic ChainOfThought
- [ ] Deterministic hallucination checker (numeric claim verification)
- [ ] Data quality confidence component only (no stability/calibration yet)
- [ ] REST API: single player prediction + basic prop comparison
- [ ] Manual prop line entry (CSV upload) — defer live odds API integration

### Phase 2 — Optimization (Weeks 7–10)
- [ ] Integrate The Odds API for live consensus lines
- [ ] Add Prop Recommender stage
- [ ] Implement multi-run stability scoring
- [ ] DSPy optimization with BootstrapFewShot (requires ~4 weeks of prediction history)
- [ ] LLM-based hallucination verification gate
- [ ] Batch prediction endpoint for full game slates

### Phase 3 — Maturation (Weeks 11–16)
- [ ] Historical calibration scoring (requires accumulated prediction data)
- [ ] MIPROv2 optimization
- [ ] PFF data integration (if licensed)
- [ ] Defense-adjusted projections
- [ ] Prediction accuracy dashboard
- [ ] College football data model extension

### Phase 4 — Scale (Weeks 16+)
- [ ] Fine-tuned smaller model evaluation (cost optimization)
- [ ] Real-time line movement alerts
- [ ] User-facing web app
- [ ] College football support (NCAA data sources)
- [ ] Backtesting framework against full historical seasons

---

## 8. Key Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM fabricates stats not in context | Critical | Data firewall + dual hallucination checking (deterministic + LLM) |
| Poor prediction accuracy | High | DSPy optimization loop; weekly evaluation; expose confidence scores transparently |
| Data source API changes/outages | Medium | Multi-source redundancy; stale data detection; graceful degradation |
| Context window overflow for data-rich players | Medium | Token budgeting; relevance filtering; summarization |
| Confidence scores are poorly calibrated | Medium | Track calibration curves; adjust weights based on observed accuracy |
| Over-reliance on model for nuanced football analysis | Medium | Combine LLM reasoning with deterministic statistical models (ensemble approach in Phase 3+) |
| Cost at scale (many LLM calls per prediction) | Medium | Cache similar predictions; batch inference; migrate to fine-tuned smaller model |

---

## 9. Extensibility Notes

**College Football Expansion:**
- The database schema is sport-agnostic by design — `player_game_stats.advanced_stats` JSONB field accommodates different stat profiles.
- College data sources (cfbfastR, ESPN college endpoints) plug into the same ETL framework.
- DSPy modules can be compiled separately for NFL vs. college — different optimized prompts for different contexts.
- Confidence calibration will need separate historical baselines (college is inherently less predictable).

**Additional Sport Support:**
- The pipeline architecture (Context Assembly → Analysis → Prediction → Recommendation) is generic. New sports require new data sources and position-specific schema fields, but the LLM pipeline structure remains the same.
