"""Database engine and session handling."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or config.DATABASE_URL
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 15} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args)
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")   # readers do not block the writer
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (registers the tables on Base)
    Base.metadata.create_all(engine)
