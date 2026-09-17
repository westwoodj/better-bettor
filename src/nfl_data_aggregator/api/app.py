"""FastAPI application factory with DB lifecycle, auth, and CORS."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Generator, Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from ..config.config import settings
from ..db.engine import get_session_factory, init_db

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize the database on startup."""
    logger.info("Initializing database...")
    init_db()
    yield


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a DB session and closes it after the request."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def verify_api_key(api_key: Optional[str] = Security(_api_key_header)) -> Optional[str]:
    """Verify the API key if one is configured in settings.

    If no API_KEY is set in the environment, all requests are allowed.
    """
    configured_key = getattr(settings, "API_KEY", None)
    if not configured_key:
        return api_key
    if api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from .routes import router

    app = FastAPI(
        title="Gridiron Oracle API",
        description="NFL player performance prediction and prop bet recommendation engine",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, dependencies=[Depends(verify_api_key)])

    return app
