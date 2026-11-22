"""A throwaway PostgreSQL database for an experiment or a test, so the real data is never touched.

`use_scratch_database()` creates an empty database next to the one DARKSTORE_DB names (same server and login, a
random name starting with `scratch_`), points DARKSTORE_DB at it and drops it when the program ends. Call it before
anything imports `app`, because the app opens its database at import time. The login needs CREATEDB, and must be
allowed to add the PostGIS extension, as the local and CI databases are.
"""
import atexit
import os
import uuid

import psycopg
from psycopg import sql

DEFAULT_URL = "postgresql://darkstore:darkstore@localhost:5432/darkstore"    # the same default as app/config.py


def _plain(url: str) -> str:
    """The URL as psycopg itself reads it: without SQLAlchemy's +psycopg, and postgres:// spelled out."""
    for prefix in ("postgresql+psycopg://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def create(base_url: str | None = None) -> tuple[str, str]:
    """Create an empty database on the same server and return (its URL, its name)."""
    base = _plain(base_url or os.getenv("DARKSTORE_DB") or DEFAULT_URL)
    name = f"scratch_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    head, _, tail = base.rpartition("/")
    query = "?" + tail.split("?", 1)[1] if "?" in tail else ""
    return f"{head}/{name}{query}", name


def drop(base_url: str, name: str) -> None:
    with psycopg.connect(_plain(base_url), autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def use_scratch_database() -> str:
    """Point this process at a new empty database and drop it at exit. Returns its URL."""
    base = _plain(os.getenv("DARKSTORE_DB") or DEFAULT_URL)
    url, name = create(base)
    os.environ["DARKSTORE_DB"] = url
    atexit.register(drop, base, name)
    return url
