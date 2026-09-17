"""SQLAlchemy engine and session factory for Gridiron Oracle."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from ..config.config import settings

_engine = None
_session_factory = None


def get_engine(url: str | None = None):
    """Return a SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None or url is not None:
        db_url = url or settings.DATABASE_URL
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(db_url, connect_args=connect_args)
    return _engine


def get_session_factory(engine=None) -> sessionmaker[Session]:
    """Return a session factory bound to the engine."""
    global _session_factory
    if _session_factory is None or engine is not None:
        eng = engine or get_engine()
        _session_factory = sessionmaker(bind=eng, expire_on_commit=False)
    return _session_factory


def init_db(url: str | None = None):
    """Create all tables defined in sa_models."""
    from . import sa_models  # noqa: F401 — ensure models are registered

    engine = get_engine(url)
    sa_models.Base.metadata.create_all(engine)
    return engine
