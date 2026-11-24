# Making a change

How to change this repository without breaking `main`, which is what staging is deployed from. How the code is
organised, and the rules it keeps, is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); read it before your first
change.

## Set up once

You need Python 3.10 or newer (the image uses 3.12), Git, and PostgreSQL 16 with PostGIS; Docker is the shortest
way to get the database. For the phone app, Node.js (22 on the dev server). For tests and deploys on AWS, the AWS
CLI and the GitHub CLI (`gh`), both signed in.

```bash
git clone https://github.com/Galabavamsi/CSL559_CSD_Group_Project.git
cd CSL559_CSD_Group_Project
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On Windows, if `python` is not found, `py` starts the same interpreter.

## Run it locally

```bash
docker compose up -d postgres          # PostgreSQL 16 with PostGIS on localhost:5432; user, password, database: darkstore
DEMO_PRODUCE=on DEMO_HUBS=on DEMO_SUPPLY=on python -m uvicorn app.main:app --reload
```

The app creates its tables and the demo data on first start. Without the three settings you get Bangalore's two
hubs with groceries only, which is what the tests and [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) expect. Open
http://localhost:8000 for the hub desk and http://localhost:8000/docs for the API. Locally the staff password is
`demo`, and a sign-in code for the phone app is written to the server's output (`EMAIL_BACKEND=log`).

`docker compose up --build` runs the app in Docker too; `docker compose --profile monitoring up --build` adds
Prometheus and Grafana. The `Makefile` has short forms: `make run`, `make test`, `make reset`.

The phone app has its own guide: [`mobile/README.md`](mobile/README.md).

## Every change, step by step

1. **Start from the latest `main`, on a branch of your own.** Branches are named `f2h/<topic>`, a few words with
   hyphens: `f2h/delivery`, `f2h/staff-sign-in`, `f2h/deploy-template`.

   ```bash
   git checkout main
   git pull
   git checkout -b f2h/release-locked-code
   ```

2. **Make one change.** A pull request that does one thing is read properly and goes back cleanly.
3. **Write or change the tests in the same branch.** A change is not done until a test shows it. A fault gets a test
   that failed before the fix.
4. **Run the checks** (next section). On AWS, `infra\test.ps1` runs all of them.
5. **Commit with a message that says what changed, in a sentence.** The body says why, if that is not obvious.

   ```text
   A deploy uses the template of the commit it deploys

   deploy.ps1 passed the working folder's app.yml to CloudFormation, so an edit in progress could ship with
   another commit's code.
   ```

6. **Push and open a pull request.** Its description has three parts: **What** (what changed, by area), **Checked**
   (what you ran and what it showed, with numbers), and **Not checked** (what you could not try, said plainly).
7. **Merge when the check "tests (AWS CodeBuild)" on the last commit is green.** Never push straight to `main`.

## The checks

**On AWS, for any branch or commit.** Needs the AWS CLI and `gh` signed in. About five minutes for the 800 tests.

```powershell
infra\test.ps1 -Ref f2h/release-locked-code
```

It runs `infra/ci-test.sh` in CodeBuild for that commit: PostgreSQL with PostGIS in a container, the migrations
built from empty and compared with `app/models.py` (`alembic check`), a syntax check of the hub pages' scripts
(`node --check web/*.js`), a type-check of the phone app, and the whole test suite. Then it sets a commit status on
GitHub named "tests (AWS CodeBuild)", so the pull request shows it. A commit that already passed is not run again;
`-Rerun` runs it anyway. Runs are not started by a push yet: [`infra/README.md`](infra/README.md) has the steps to
switch that on.

**On your own machine,** with a PostGIS database the tests may wipe. They empty every table of the database they
are given before each test: never point them at data you want to keep.

```bash
docker compose up -d postgres
DARKSTORE_TEST_DB=postgresql://darkstore:darkstore@localhost:5432/darkstore python -m pytest -q
```

They do not run on the owner's Windows laptop, where Application Control blocks the compiled `h3` library; use
`infra\test.ps1` there. With Docker you can also run exactly what AWS runs: `bash infra/ci-test.sh` (it starts its
own PostGIS on port 5432, so stop the compose database first).

**The phone app's type-check,** when you change anything in `mobile/`:

```bash
cd mobile
npm ci
npx tsc --noEmit
```

On Windows, in PowerShell, type `npm.cmd` and `npx.cmd` in place of `npm` and `npx`.

**The hub pages' scripts,** when you change `web/`: `node --check web/app.js` (and the others), then open the page
and use it. Pages are plain JavaScript with no build step; a browser may keep the old script, so reload with
Ctrl+Shift+R.

## When you change the database tables

Table changes are migrations (Alembic), numbered `0001` to `0009` so far, in `migrations/versions/`. The app applies
any new ones when it starts (`alembic upgrade head`, in `app/db.py`), so deploying new code is enough to change
staging's tables. An empty database gets its tables straight from `app/models.py`.

**Once a migration has been applied anywhere shared (staging, or a database someone else uses), never edit it. Add
a new one.** An edited migration is not run again where it already ran, so that database and the code disagree
from then on. It happened on 24 November: a column was added to migration 0007 after it had run on the dev server's
test database, which then said it was up to date, lacked the column, and failed thirteen tests
([`docs/journal/2026-11-24-orders-on-the-server.md`](docs/journal/2026-11-24-orders-on-the-server.md)).

After editing `app/models.py`, against a local database:

```bash
python -m alembic upgrade head                                                # your database at the newest one
python -m alembic revision --autogenerate --rev-id 0010 -m "release locked door codes"
python -m alembic upgrade head                                                # apply the new one
python -m alembic check                                                       # nothing left between models and migrations
```

The next number follows the last file in `migrations/versions/`. Then:

1. **Read the new file before you commit it.** Autogenerate cannot tell a rename from a drop and an add (edit it to
   `alter_column` or `rename_table`, or that column's data is lost), and it does not fill a new required column for
   rows that already exist (give it a `server_default`, or make it nullable).
2. **Commit the migration in the same pull request as the model change.** `tests/test_migrations.py` and the AWS run
   fail when `models.py` and the migrations disagree.

Both commands use the database in `DARKSTORE_DB` (default
`postgresql://darkstore:darkstore@localhost:5432/darkstore`).

## Rules that protect everyone

- **Never commit a secret, an AWS account id, a server id or a bucket name.** The repository is public. Passwords,
  keys and tokens live in AWS Secrets Manager and are named, never quoted. `deploy.env` and `.env` files are
  git-ignored; keep them that way.
- **Only `app/modules/inventory/service.py` changes stock quantities.** A new kind of stock change is a new function
  there, with its ledger row.
- **A state change is one guarded update, and what must happen together shares a transaction.**
  `docs/ARCHITECTURE.md` sections 4 to 6 say what that means in this code.
- **Do not change an existing endpoint's request or answer.** The phone app and the hub pages read them, and an
  installed app cannot be changed in step with the server. Adding a field is fine; renaming or removing one is not.
- **New settings go in `app/config.py`,** off or at a safe value by default, with a comment saying what they do. A
  setting for staging goes in `infra/app.yml` too.
- **A calendar date comes from `app/clock.py`,** never from the server's clock.
- **Name things as the code does** (`hold`, `pick job`, `trip`, `hub`), and write a docstring on every service
  function saying what it does, what it refuses and whether it commits.

## Write down what you did and why

- **A decision** (a rule, a number, a library, something deliberately not done) goes in
  [`docs/DESIGN.md`](docs/DESIGN.md), with what was decided, why, what else was considered, and what it costs. Change
  an existing section rather than contradict it.
- **A journal entry** for each piece of work goes in [`docs/journal/`](docs/journal/README.md), named
  `YYYY-MM-DD-short-title.md`: what was built, the decisions, what went wrong, what was checked, what is left open,
  and sources. A fact from outside the project gets a link; a fact we measured says how. Add it to the index in
  `docs/journal/README.md`.
- If you change how something is run, change the guide that says so: this file, `docs/ARCHITECTURE.md`,
  `infra/README.md`, `mobile/README.md` or `docs/HANDOVER.md`.

## Deploying

Merged is not deployed. Staging is deployed by hand from AWS, never by a push:

```powershell
infra\deploy.ps1 -Env staging -Ref main
```

[`infra/README.md`](infra/README.md) says what it does and how to check the result.

## Getting unstuck

1. Read the function's docstring and the test that covers it.
2. Reproduce the problem in a test; a failing test is the best bug report.
3. Look in [`docs/DESIGN.md`](docs/DESIGN.md) for why the rule is the way it is, and in
   [`docs/journal/`](docs/journal/README.md) for when it was built and what went wrong then.
4. [`docs/HANDOVER.md`](docs/HANDOVER.md) lists the known faults; yours may be one of them.
