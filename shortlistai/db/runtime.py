from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Mapping

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "shortlistai.db"
_ENGINE_LOCK = threading.Lock()
_ENGINES: dict[str, Engine] = {}


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


def get_engine_for_url(url: str) -> Engine:
    """Return one reusable engine per normalized database URL."""
    database_url = normalize_database_url(url)
    if not database_url:
        raise ValueError("Database URL is required")
    with _ENGINE_LOCK:
        engine = _ENGINES.get(database_url)
        if engine is None:
            engine = create_database_engine(database_url)
            _ENGINES[database_url] = engine
        return engine


def get_database_engine() -> Engine:
    """Return the reusable engine for the currently configured database."""
    return get_engine_for_url(resolve_database_url())


def dispose_cached_engines() -> None:
    """Dispose all pooled connections and clear cached engines."""
    with _ENGINE_LOCK:
        engines = list(_ENGINES.values())
        _ENGINES.clear()
    for engine in engines:
        engine.dispose()
