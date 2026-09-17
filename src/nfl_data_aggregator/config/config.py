from typing import Optional
import os

# Try pydantic-settings (pydantic v2) first, then fall back to pydantic v1, then minimal impl
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field, ConfigDict
    _HAS_PYDANTIC_V2 = True
except Exception:
    _HAS_PYDANTIC_V2 = False
    try:
        from pydantic import BaseSettings, Field
    except Exception:
        BaseSettings = object

        def Field(default=None, env: Optional[str] = None, **kwargs):
            return default


class Settings(BaseSettings):
    # Google GenAI API key (or path to credential file depending on your setup)
    GOOGLE_GENAI_API_KEY: Optional[str] = os.environ.get("GOOGLE_GENAI_API_KEY")
    # default model to use
    GOOGLE_GENAI_MODEL: str = os.environ.get("GOOGLE_GENAI_MODEL", "models/text-bison-001")

    # Example adapters keys (placeholders)
    SPORTS_DATA_API_KEY: Optional[str] = os.environ.get("SPORTS_DATA_API_KEY")
    ODDS_API_KEY: Optional[str] = os.environ.get("ODDS_API_KEY")

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///gridiron_oracle.db")

    # DSPy / LLM configuration
    DSPY_LM_PROVIDER: str = os.environ.get("DSPY_LM_PROVIDER", "anthropic")
    ANTHROPIC_API_KEY: Optional[str] = os.environ.get("ANTHROPIC_API_KEY")
    OPENAI_API_KEY: Optional[str] = os.environ.get("OPENAI_API_KEY")
    DSPY_MODEL: str = os.environ.get("DSPY_MODEL", "claude-sonnet-4-20250514")
    DSPY_TEMPERATURE_ANALYSIS: float = float(os.environ.get("DSPY_TEMPERATURE_ANALYSIS", "0.3"))
    DSPY_TEMPERATURE_PREDICTION: float = float(os.environ.get("DSPY_TEMPERATURE_PREDICTION", "0.1"))

    # NFL data
    NFL_SEASON: int = int(os.environ.get("NFL_SEASON", "2025"))

    if _HAS_PYDANTIC_V2:
        model_config = ConfigDict(env_file=".env")
    else:
        class Config:
            env_file = ".env"


# instantiate settings (with pydantic this will validate; without it the class
# simply holds the attributes we set above)
settings = Settings()
