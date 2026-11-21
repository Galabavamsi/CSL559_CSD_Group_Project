"""Migrations (Member 1 guide, task 1.7): the steps in migrations/versions must build the tables models.py describes.

Each test works on its own empty SQLite file, whichever database the rest of the suite runs on. On PostgreSQL the
same check is `python -m alembic upgrade head && python -m alembic check` against an empty database (CI runs it)."""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app import config, db
from app.db import ALEMBIC_INI, Base, make_engine


@pytest.fixture()
def empty_engine(tmp_path, monkeypatch):
    """`app.db` pointed at a new, empty database file for one test."""
    engine = make_engine(f"sqlite:///{tmp_path.as_posix()}/migrations.db")
    monkeypatch.setattr(db, "engine", engine)
    yield engine
    engine.dispose()


def _version(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _head() -> str:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


def _differences(engine) -> list:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def test_the_migrations_build_exactly_the_tables_in_models(empty_engine):
    """If this fails you changed app/models.py without a migration: run
    `python -m alembic revision --autogenerate -m "..."` and commit the new file."""
    alembic = Config(str(ALEMBIC_INI))
    with empty_engine.begin() as connection:
        alembic.attributes["connection"] = connection
        command.upgrade(alembic, "head")

    assert _differences(empty_engine) == []
    assert _version(empty_engine) == _head()


def test_a_new_database_gets_its_tables_and_is_marked_as_up_to_date(empty_engine):
    db.init_db()

    assert set(Base.metadata.tables) <= set(inspect(empty_engine).get_table_names())
    assert _version(empty_engine) == _head()
    assert _differences(empty_engine) == []


def test_a_database_from_before_migrations_is_adopted_and_keeps_its_data(empty_engine):
    # The tables as the code just before migrations made them, which is migration 0001 without its version record.
    # (Not Base.metadata.create_all: models.py has moved on since, so that would build tables the old code never had.)
    alembic = Config(str(ALEMBIC_INI))
    with empty_engine.begin() as connection:
        alembic.attributes["connection"] = connection
        command.upgrade(alembic, db.FIRST_MIGRATION)
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("INSERT INTO stores (name, lat, lng, radius_km, status, hub_name) "
                                "VALUES ('Old store', 1, 2, 3, 'open', 'Hub')"))
    assert _version(empty_engine) is None

    db.init_db()
    db.init_db()                                                # starting the app again changes nothing

    assert _version(empty_engine) == _head()
    assert _differences(empty_engine) == []                     # every later migration was applied
    with empty_engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM stores")) == "Old store"


def test_hosted_database_urls_are_opened_with_the_installed_driver():
    assert config._database_url("postgres://u:p@host:5432/db") == "postgresql+psycopg://u:p@host:5432/db"
    assert config._database_url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert config._database_url("postgresql+psycopg://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert config._database_url("sqlite:///./darkstore.db") == "sqlite:///./darkstore.db"
