from typing import Optional
import os

# Try to use pydantic's BaseSettings if available for richer behavior; otherwise
# fall back to a minimal Settings implementation so the package is importable
# without external dependencies (useful for development and static checks).
try:
    from pydantic import BaseSettings, Field
except Exception:
    BaseSettings = object

    def Field(default=None, env: Optional[str] = None):
        # lightweight sentinel for defaults; callers read environment manually
        return default


class Settings(BaseSettings):
    # Google GenAI API key (or path to credential file depending on your setup)
    GOOGLE_GENAI_API_KEY: Optional[str] = os.environ.get("GOOGLE_GENAI_API_KEY")
    # default model to use
    GOOGLE_GENAI_MODEL: str = os.environ.get("GOOGLE_GENAI_MODEL", "models/text-bison-001")

    # Example adapters keys (placeholders)
    SPORTS_DATA_API_KEY: Optional[str] = os.environ.get("SPORTS_DATA_API_KEY")
    ODDS_API_KEY: Optional[str] = os.environ.get("ODDS_API_KEY")

    class Config:
        env_file = ".env"


# instantiate settings (with pydantic this will validate; without it the class
# simply holds the attributes we set above)
settings = Settings()

