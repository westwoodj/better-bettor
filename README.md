NFL Data Aggregator

Purpose

This project is a lightweight framework to collect "source truth" datasets (official league data and odds providers), extract features for an NFL matchup, and use Google GenAI to recommend betting lines (spread, moneyline, total, and player props).

Project layout

- src/nfl_data_aggregator/
  - __init__.py
  - config.py         # environment/config loader
  - models.py         # pydantic domain models
  - clients/
    - google_genai_client.py  # thin wrapper for Google GenAI
  - adapters/
    - sportsdata.py   # example external data adapter
    - odds_api.py     # example odds provider adapter
    - source_truth.py # loader for local/authoritative datasets
  - services/
    - recommendation_service.py # core logic to combine data and call model
- examples/run_sample.py    # example usage (does not call live APIs by default)
- tests/test_models.py      # a couple of tiny unit tests
- requirements.txt

Notes & next steps

- Add your API keys to a `.env` file or to your environment (see `src/nfl_data_aggregator/config.py`).
- Install dependencies from `requirements.txt`.
- Implement real adapters for the providers you prefer (SportsDataIO, Sportradar, TheOddsAPI, etc.).
- Tune prompts and parsing in `GoogleGenAIClient` and `services/recommendation_service.py`.

Security

Do not commit API keys. Use environment variables or a secrets manager.

