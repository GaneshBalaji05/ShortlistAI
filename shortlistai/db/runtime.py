from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "shortlistai.db"


def normalize_database_url(url: str) -> str:
    value = (url or "").strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://") and not value.startswith("postgresql+psycopg://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def resolve_database_url(env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ
    configured = normalize_database_url(source.get("DATABASE_URL", ""))
    if configured:
        return configured

    sqlite_path = source.get("SQLITE_PATH", "").strip()
    path = Path(sqlite_path) if sqlite_path else DEFAULT_SQLITE_PATH
    return f"sqlite:///{path.resolve()}"


def is_postgres_url(url: str) -> bool:
    normalized = normalize_database_url(url)
    return normalized.startswith("postgresql+psycopg://")


def create_database_engine(url: str | None = None) -> Engine:
    database_url = normalize_database_url(url or resolve_database_url())
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite:///"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    return create_engine(database_url, **kwargs)


@lru_cache(maxsize=8)
def _cached_engine(database_url: str) -> Engine:
    return create_database_engine(database_url)


def get_database_engine() -> Engine:
    """Return a reusable engine for the currently configured database URL.

    The normalized URL is the cache key, so tests or controlled cutovers that change
    ``DATABASE_URL`` get a separate engine instead of accidentally reusing the old target.
    """

    return _cached_engine(normalize_database_url(resolve_database_url()))


def dispose_cached_engines() -> None:
    """Dispose cached engines and clear the cache (primarily for tests/cutover tooling)."""

    cache = _cached_engine.cache_info()
    if cache.currsize:
        # functools does not expose cached values, so clear first; engines also release
        # connections when their process exits. Explicit disposal remains available on any
        # engine returned to callers that need deterministic teardown.
        _cached_engine.cache_clear()
    else:
        _cached_engine.cache_clear()
