"""Alembic environment: which database to migrate and which tables it should end up with.

The database is the app's own engine (DARKSTORE_DB, see app/config.py), so there is no second place to configure it.
`render_as_batch` is left over from SQLite; on PostgreSQL it changes nothing and the first migrations use it.
`include_object` keeps PostGIS's own table out of the comparison with models.py. app/db.py and the tests pass their
own connection in through `config.attributes`.
"""
from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base, engine, include_object

OPTIONS = {"target_metadata": Base.metadata, "render_as_batch": True, "compare_type": True,
           "include_object": include_object}


def _migrate(connection) -> None:
    context.configure(connection=connection, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():            # `alembic upgrade head --sql`: print the SQL instead of running it
    context.configure(url=engine.url.render_as_string(hide_password=False), literal_binds=True, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    _migrate(context.config.attributes["connection"])
else:
    with engine.connect() as connection:
        _migrate(connection)
