"""Database engine (PostgreSQL + PostGIS), session handling, and bringing the tables up to date (migrations)."""
import threading
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


LOCK_WAIT_SECONDS = 15       # a statement blocked by another transaction for this long fails instead of hanging


def make_engine(url: str | None = None):
    """PostgreSQL through psycopg 3. `url` is for tools that need a second database (tests, scratch runs)."""
    url = config._database_url(url) if url else config.DATABASE_URL
    return create_engine(
        url, pool_size=config.DB_POOL_SIZE, max_overflow=config.DB_POOL_OVERFLOW,    # see config.py for why
        pool_pre_ping=True,       # a connection the server dropped (restart, idle cut-off) is replaced, not used
        # search_path: only our own schema. The postgis Docker image also installs a US address geocoder and puts
        # its `tiger` schema on the database's search path; its ~35 tables then looked like ours to Alembic and to
        # the "is this database empty?" check below.
        connect_args={"options": f"-c lock_timeout={LOCK_WAIT_SECONDS * 1000} -c search_path=public"})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------------------------------- tables and migrations
#
# The tables are described twice: app/models.py says what they are now, and migrations/versions/ holds the steps
# that take an existing database from one shape to the next (Alembic). tests/test_migrations.py fails if the two
# disagree. See "When you change the database tables" in CONTRIBUTING.md.

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
FIRST_MIGRATION = "0001"     # the tables as they were when migrations were added
MIGRATION_LOCK = 559_001     # any fixed number: the PostgreSQL advisory lock that app instances take to migrate
_one_thread = threading.Lock()   # Alembic keeps its state in module globals, so one thread at a time in a process


def _alembic(connection, command_name: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    config_ = Config(str(ALEMBIC_INI))
    config_.attributes["connection"] = connection      # migrations/env.py uses this instead of opening its own
    getattr(command, command_name)(config_, revision)


POSTGIS_TABLES = {"spatial_ref_sys"}     # created by the PostGIS extension, not by us


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """For Alembic's comparison of the database with models.py: PostGIS's own table is not ours to add or drop."""
    return not (type_ == "table" and name in POSTGIS_TABLES)


def _bring_up_to_date(recreate: bool) -> None:
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from alembic.config import Config

    from . import models  # noqa: F401  (registers the tables on Base)

    with _one_thread, engine.begin() as connection:
        # Several app instances may start together: the first migrates, the others wait here and then find
        # nothing left to do. Released when this transaction ends.
        connection.execute(text("SELECT pg_advisory_xact_lock(:n)"), {"n": MIGRATION_LOCK})
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))    # location columns need its types
        tables = set(inspect(connection).get_table_names()) - POSTGIS_TABLES
        if recreate and "alembic_version" in tables:
            head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
            if MigrationContext.configure(connection).get_current_revision() == head:
                # The tables are already the newest: empty them instead of dropping and creating ~30 tables, which
                # took most of each test's time. TRUNCATE holds other requests back until this commits, so nobody
                # finds a table missing (issue #59), and ids start at 1 again.
                names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
                connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
                return
        if recreate or not tables - {"alembic_version"}:
            if recreate:
                Base.metadata.drop_all(connection)
            Base.metadata.create_all(connection)
            _alembic(connection, "stamp", "head")
            return
        if "alembic_version" not in tables:
            _alembic(connection, "stamp", FIRST_MIGRATION)
        _alembic(connection, "upgrade", "head")


def recreate_tables() -> None:
    """Empty the database for seed.reset, with every table as models.py describes it and ids starting at 1.

    Tables already at the newest migration are emptied in place; anything older is dropped and created again. Either
    way it is one transaction, so the timed jobs and other requests wait instead of finding no tables."""
    _bring_up_to_date(recreate=True)


def init_db() -> None:
    """Called when the app starts. An empty database gets its tables; an existing one is migrated to the newest
    version (`alembic upgrade head`), so deploying new code and restarting is enough.

    A database made before migrations existed has tables but no version record. It is taken to be at the first
    migration, which is true if it was created by the code just before migrations were added; an older file than
    that must be deleted and recreated, as the rule was until now."""
    _bring_up_to_date(recreate=False)
