# Working on this repo

Four people share this codebase. These rules keep `main` working at all times, so that anyone
can demo from it on any day.

## One-time setup

```bash
git clone <your-repo-url>
cd darkstore
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                   # every test must pass before you start
```

## Daily workflow

1. **Start from the latest main.**
   ```bash
   git checkout main && git pull
   git checkout -b m2/cancel-after-payment        # m<your member number>/<short task name>
   ```
2. **Make one task's worth of changes.** Small branches are reviewed faster and conflict less.
3. **Write or update tests in the same branch.** A task is not done until a test proves it.
4. **Run the checks.**
   ```bash
   python -m pytest -q
   ```
5. **Commit with a message that says what changed and why.**
   ```
   Inventory: release expired holds automatically every 30 seconds

   The sweep used to run only when someone called the admin endpoint.
   ```
6. **Push and open a pull request.** Ask one teammate to review. If you changed a function or
   endpoint that another member uses (see "Contracts" in `docs/TEAM_PLAN.md`), ask *that* member.
7. **Merge when the tests are green and one teammate has approved.** Delete the branch.

## Rules that protect everyone

- **Never push straight to `main`.** Turn on branch protection in the GitHub settings.
- **Only `app/modules/inventory/service.py` writes to the stock tables** (`StockLevel`, `StockItem`,
  `StockLedger`). If you need a new kind of stock change, ask Member 1 for a function.
- **Call other modules through their `service.py` functions or through events**, never by reaching
  into their tables.
- **Every stock change writes a ledger row.** `assert_stock_is_consistent()` in `tests/conftest.py`
  checks this; call it at the end of any test that moves stock.
- **Do not change an existing endpoint's request or response shape** without telling the team.
  Adding new fields is fine; renaming or removing them breaks the demo screens and other members' tests.
- **Put new settings in `app/config.py`**, not as numbers scattered in the code.

## When you change the database tables

Table changes are migrations (Alembic), so an existing database, including the hosted one, is
changed in place and keeps its data. After editing `app/models.py`, two commands:

```bash
python -m alembic revision --autogenerate -m "add shelf_life to bins"   # writes migrations/versions/<id>_....py
python -m alembic upgrade head                                           # applies it to your database
```

1. **Read the new file before you commit it.** Autogenerate sees added and removed tables, columns
   and indexes. It cannot tell a rename from a drop plus an add (edit it to `alter_column` /
   `rename_table`, or the data in that column is lost), and it does not fill a new required column
   for rows that already exist (give it a `server_default`, or add it as nullable).
2. **Commit the migration in the same pull request as the model change.**
   `tests/test_migrations.py` fails when `models.py` and the migrations disagree.
3. **Nobody has to delete `darkstore.db` any more.** The app runs `upgrade head` itself when it
   starts, so pulling `main` and restarting is enough. A new, empty database gets its tables
   straight from `models.py`.

Both commands use the database in `DARKSTORE_DB` (default: `postgresql://darkstore:darkstore@localhost:5432/darkstore`).
The tests build their tables from `models.py`, so they never need a migration to be run.

The tests need PostgreSQL with PostGIS, and empty every table in that database before each test:

```bash
docker compose up -d postgres
python -m pytest -q          # or DARKSTORE_TEST_DB=postgresql://... for a database somewhere else
```

CI runs the suite on AWS (`infra/test.ps1`; see `infra/README.md`).

## Code style

- Business logic goes in `service.py` as plain functions that take a `db` session first.
  Routers only parse input, call one service function, and shape the output.
- Raise `DomainError(status, code, message)` for business-rule failures. Do not return error
  dictionaries with a 200 status.
- Name things after the HLD (`reservation`, `transfer order`, `pick task`) so the code and the
  document read the same.
- Write a docstring on every service function saying what it does and whether it commits.

## Getting unstuck

1. Read the function's docstring and the test that covers it.
2. Reproduce the problem in a test; a failing test is the best bug report.
3. Ask the member who owns the module (table in `docs/TEAM_PLAN.md`).
