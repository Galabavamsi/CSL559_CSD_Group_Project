# CI failed on tables we never created

*23 November 2026. The first pull request of the rebuild failed in CI although the whole suite had passed on the
dev server.*

## Context

The pull request moved the tests to the `postgis/postgis:16-3.4` Docker image. CI starts that image with
`POSTGRES_DB=darkstore`, runs `alembic upgrade head`, then `alembic check`, which compares the tables in the database
with the tables `app/models.py` describes and fails if they differ.

## What happened

`alembic check` failed with:

```
FAILED: New upgrade operations detected: [('remove_table', Table('bg', MetaData(),
  Column('gid', INTEGER(), ...), Column('statefp', VARCHAR(length=2), ...
```

Alembic had found a table called `bg` and concluded that a migration should remove it. We have no such table.

## Cause

`bg` belongs to the TIGER geocoder, a United States address geocoder that ships with PostGIS. The official PostGIS
Docker image installs it in the default database, together with `postgis` and `postgis_topology`. On a fresh
container we then read the database's search path:

```
$ psql -U darkstore -d darkstore -tAc "SHOW search_path"
"$user", public, topology, tiger
```

So `tiger` is on the search path of the image's default database. SQLAlchemy, asked for "the tables" with no schema
named, returns every table visible through the search path, and the geocoder's tables came back beside ours.

The `tiger` schema of a fresh container holds 34 tables. Two things went wrong because of them, not one:

1. `alembic check` reported those tables as tables to remove. This is the failure CI showed.
2. When the app starts, it decides whether a database is new by asking whether it has any tables. A new database
   from this image looked old. CI never reached this, so we tried it: starting the app's database set-up
   (`db.init_db()`) with the code from before the fix against a fresh container failed with a database
   `ProgrammingError`. The first `docker compose up` would have failed the same way.

## Why the dev server did not show it

On the dev server the `darkstore` database had been dropped and created again by hand before the test run, to start
clean. A database made with `CREATE DATABASE` gets neither the geocoder nor the changed search path; only the
database the image creates at first start does. The dev server was testing a cleaner database than CI or a new
deployment would ever see.

## Fix

Every connection the app opens now sets `search_path=public`, next to the lock timeout it already set
(`app/db.py`, `make_engine`). The app sees only its own schema, whatever else is installed in the database.

Checked on fresh `postgis/postgis:16-3.4` containers, started exactly as CI starts them:

- `alembic upgrade head` and `alembic check` report no differences, and the full suite passes (610 tests).
- `db.init_db()` with the fix succeeds and leaves 26 tables in `public` (ours and Alembic's version table).
- `docker compose up --build` from nothing: the app starts, loads the demo data and answers `/v1/cities`,
  `/v1/stores?city=bangalore` and `/v1/serviceability`, with no error in its log.
- CI on the pull request passes.

## What it taught

- Reproduce CI with a fresh container, not with a database that has been tidied by hand.
- "The tables in this database" is not a fixed set in PostgreSQL: it depends on the search path of the connection.
  An app that owns one schema should say so on its connections.
- A check that only compares (`alembic check`) caught a problem that would otherwise have appeared as a failed first
  start in production.

## Sources

- The official PostGIS Docker image, which documents the extensions it installs in the default database
  (`postgis`, `postgis_topology`, and `postgis_tiger_geocoder` for PostGIS before 3.7):
  https://github.com/postgis/docker-postgis
- Seen ourselves, not taken from a document: the search path and the count of 34 tables, read from a fresh
  `postgis/postgis:16-3.4` container; the CI log line quoted above; and the failed and successful first starts.
