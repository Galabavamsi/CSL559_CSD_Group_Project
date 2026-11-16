# Working on this repo

Four people share this codebase. These rules keep `main` working at all times, so that anyone
can demo from it on any day.

## One-time setup

```bash
git clone <your-repo-url>
cd darkstore
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                   # must print "45 passed" before you start
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

The prototype creates tables on start-up but does not migrate them. After editing `app/models.py`:

```bash
rm darkstore.db          # Windows: del darkstore.db
python -m uvicorn app.main:app --reload      # recreates tables and demo data
```

Say in your pull request that the database must be recreated. (Member 1 has a task to add real
migrations; after that this section changes.)

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
