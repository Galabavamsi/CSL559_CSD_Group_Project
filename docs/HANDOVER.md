# Handover

*Written on 24 November 2026 for whoever takes this project on next. It says what the system is, where it stands,
where everything lives, how to run, change, test, deploy and build it, who holds what, and what is known to be
wrong. Read it once from top to bottom, then use it as a reference.*

*Where it points elsewhere, the other document is the longer version: the reasons behind every decision are in
[`DESIGN.md`](DESIGN.md); how the code is put together is in [`ARCHITECTURE.md`](ARCHITECTURE.md); what happened
each day, including what went wrong, is in [`journal/`](journal/README.md). Nothing here is a secret: the
repository is public, and passwords and keys are named by where they are kept, never by value.*

## Contents

1. [The project in one page](#1-the-project-in-one-page)
2. [Where it stands](#2-where-it-stands)
3. [Where to see it](#3-where-to-see-it)
4. [The repository, folder by folder](#4-the-repository-folder-by-folder)
5. [How it works](#5-how-it-works)
6. [The API, module by module](#6-the-api-module-by-module)
7. [Settings](#7-settings)
8. [Environments](#8-environments)
9. [Access: who holds what](#9-access-who-holds-what)
10. [How to: the everyday tasks](#10-how-to-the-everyday-tasks)
11. [Tests](#11-tests)
12. [The phone app](#12-the-phone-app)
13. [Known faults, limits and risks](#13-known-faults-limits-and-risks)
14. [What to do next](#14-what-to-do-next)
15. [Before the demo on 3 December](#15-before-the-demo-on-3-december)
16. [Loose ends at the moment of handover](#16-loose-ends-at-the-moment-of-handover)
17. [History](#17-history)
18. [Words used here](#18-words-used-here)

---

## 1. The project in one page

**JustInTimeFarm2Home** moves produce from farms to homes through small local hubs (micro-warehouses).

1. A **farmer** lists a lot from a phone: what, how many kilograms, when it was picked. The system chooses the
   nearest hub with room and gives a morning drop slot.
2. At the hub, a **receiver** weighs the lot and grades it, and the accepted kilograms become whole units that
   customers buy (a 500 g pack, a bunch, a piece). Each portion goes into the bin the screen names and is on sale
   from that moment.
3. A **customer** chooses where to deliver. The hub whose zone covers that address serves it, and the shop shows
   only what that hub can deliver now, with each pack's grade, harvest date, use-by date and farm. A batch in its
   last day is 30% cheaper. The cart is held for ten minutes while the customer pays.
4. A **picker** at the hub takes the order, walks the bins oldest batch first, scans every unit, and packs the bag
   into a crate slot.
5. A **delivery agent** on duty is given a trip of packed orders that lie in the same direction, checks the bags
   out of the hub, and at each door types in the four digits the customer reads out.

It runs for two cities: **Bhilai** (tier 2; four hubs, one beside IIT Bhilai) and **Bangalore** (tier 1; two
hubs). The live demo is on **3 and 4 December 2026 in Bhilai**.

It is one Python program (FastAPI) with a PostgreSQL database that understands geography (PostGIS), plain web
pages for the hub's staff, and one phone app (Expo, React Native) for customers, farmers and delivery agents. A
copy called **staging** runs on AWS in Mumbai. There is no production.

It began as a university group project (CSL559): a dark-store prototype built by four students, whose stock,
picking and restocking code is still the base. That prototype as the group left it is the git tag
`darkstore-final`. From 23 November it was rebuilt by one person into what is described here.

## 2. Where it stands

On 24 November 2026, **800 automated tests** pass on AWS, and staging runs the code they test.

### Built and working end to end

| Area | What works | Checked by |
| --- | --- | --- |
| Accounts | Sign-in by a six-digit code sent by email, with limits per address; sessions that renew; staff logins by password | Tests; real codes sent from staging |
| Cities and hubs | Two cities, six hubs; delivery zones as H3 cells; opening a hub in one step; a customer outside every zone can ask for delivery | Tests; staging |
| Farm supply | Farms, listings, the nearest hub with room, drop slots, weighing and grading into units, a farm's rejection rate | Tests; end-to-end run |
| Stock | Holds that cannot oversell, oldest batch first, expiry, counts, a ledger and an audit, restocking packaged goods from a warehouse | Tests (twenty buyers race for one unit); end-to-end run |
| The shop | What a hub can deliver now, with the facts of the batch picked next and the rescue price | Tests; staging |
| Orders | An order written inside the payment, priced by the batches picked, the hub's own bill at checkout, a refused price rise, cancel until packed | Tests; end-to-end run |
| Picking and packing | One order, or three in one walk; barcode checks; empty shelves; substitutes; packing commits the sale | Tests; end-to-end run |
| Delivery | Trips formed by a pooling rule, the shortest order of stops, the agent free longest, bags checked out, a door code stored nowhere, failed hand-overs | Tests; end-to-end run (one stop) |
| Hub pages | Hub desk, ops dashboard, intake, picker, network map; a shared staff sign-in box | End-to-end run; three browsers signed in at once |
| Phone app | One app, three roles; installs on Android from a file | Its web build in the end-to-end run; installed and started on one phone |
| AWS | Staging on ECS Fargate; RDS with a standby; load balancer with a web firewall; tests and builds on CodeBuild | Deploys; a smoke test; a forced database failover on 23 November |

### Built but not checked

- **An order placed from the installed Android app.** It was installed and started on one phone; signing in and
  ordering from it had not been done at handover. Everything behind it has run through the app's web build.
- **A trip with several stops, end to end.** The tests cover it; the recorded run had one order.
- **Load on the new code.** The load test is from 23 November and does not call orders or delivery.

### Not built

A map in the app and the agent's position; a time of arrival; real payment; what the hub does with a bag that
comes back undelivered; releasing a door code locked by wrong tries; the dispatch panel as a page (it is an API);
hubs asking farms for what they expect to sell; the simulated day that would say whether pooling pays. Section 14
puts them in order, and [`DESIGN.md`](DESIGN.md) sections 4.10 and 6 say why each was left.

### Numbers

Every measured number, with its date and method, is in the report ([`handbook/`](handbook/README.md), section 4).
The main ones: 800 tests; one end-to-end run of nine passes from a farmer's listing to the customer's door; an
order packed with nobody at the hub in 50 seconds; staging's last 24 hours with no server errors. **One target is
missed:** the shop's read took 130 ms at the 99th percentile under load, against a target of 100 ms (a load test on
the development server, one machine, 23 November).

## 3. Where to see it

| What | Where | Sign-in |
| --- | --- | --- |
| Phone app for Android | [Release `app-staging-2026-11-24`](https://github.com/Galabavamsi/CSL559_CSD_Group_Project/releases/tag/app-staging-2026-11-24) | An email address; a code is sent to it |
| Hub desk: customer, picker and store side by side, with live events | https://staging.farm2home.galabavamsi.com/ | Staff password |
| Ops dashboard | https://staging.farm2home.galabavamsi.com/ops.html | Staff password |
| Intake (receiver), at BH-04 IIT Bhilai | https://staging.farm2home.galabavamsi.com/intake.html?store=6 | Staff password |
| Picker, at BH-04 IIT Bhilai | https://staging.farm2home.galabavamsi.com/picker.html?store=6 | Staff password |
| Network map, Bhilai | https://staging.farm2home.galabavamsi.com/network.html?city=bhilai | Staff password |
| The API, every call with a form to try it | https://staging.farm2home.galabavamsi.com/docs | None to read; a token to call |
| The report | [`handbook/JustInTimeFarm2Home-handbook.pdf`](handbook/JustInTimeFarm2Home-handbook.pdf) | |
| How to show it from phones | [`DEMO_ON_A_PHONE.md`](DEMO_ON_A_PHONE.md) | |

Hub numbers: 1 DS-01 Central and 2 DS-02 North in Bangalore; 3 BH-01 Civic Centre, 4 BH-02 Nehru Nagar, 5 BH-03
Durg and 6 BH-04 IIT Bhilai in Bhilai. On the hub desk and the dashboard the hub is chosen from a menu at the top.

Any number of people can use the hub pages at once, each on their own device. Each browser asks for the staff
password once and remembers it.

**Some networks block the staging address**, among them the developer's laptop network and the campus Wi-Fi at
IIT Bhilai. The app and the pages then fail to connect. Mobile data works.

## 4. The repository, folder by folder

| Path | What it holds | Notes |
| --- | --- | --- |
| `app/` | The backend | One FastAPI application |
| `app/modules/<name>/` | One package per service: `service.py` holds the rules, `router.py` the HTTP endpoints | Section 6 lists them |
| `app/main.py` | Builds the app, plugs in every module, starts the timed jobs | |
| `app/config.py` | Every setting, read from the environment, with its default and the reason for it | Section 7 |
| `app/models.py` | Every table | A change needs a migration |
| `app/events.py` | The event bus: events go to an outbox table in the same transaction as the change, then to the live feed | Stands in for Kafka |
| `app/clock.py` | Today's date where the hubs are (India) | Never take a date from the server's clock |
| `app/background.py` | The timed jobs | Section 5 |
| `app/seed.py` | Demo data: cities, hubs, groceries, produce, staff logins | |
| `app/demo_supply.py`, `app/demo_hub.py` | Staging's stand-ins for farmers and pickers | Off unless switched on |
| `migrations/versions/` | Database changes 0001 to 0009, applied when the app starts | Never edit one that has run anywhere shared |
| `tests/` | 63 test files | Need PostgreSQL with PostGIS; section 11 |
| `web/` | The hub's pages: plain HTML, CSS and JavaScript, no build step | Served by the backend |
| `mobile/` | The phone app | [`mobile/README.md`](../mobile/README.md) |
| `infra/` | AWS: five CloudFormation templates, and the scripts that test, deploy and smoke-test | [`infra/README.md`](../infra/README.md) |
| `scripts/` | The end-to-end recorder, the app build, load tests, experiments, demo data | Section 10 |
| `monitoring/` | Prometheus and Grafana, for running locally with Docker | Not used on AWS |
| `docs/DESIGN.md` | Every decision, with what was considered and what it costs | Read before changing a rule |
| `docs/ARCHITECTURE.md` | How the code is organised and the rules it keeps | Read before writing code |
| `docs/journal/` | One entry per piece of work: what was built, what went wrong, sources | Add one per change |
| `docs/handbook/` | The report (PDF) and the HTML it is printed from | |
| `docs/DEMO_ON_A_PHONE.md`, `docs/DEMO_SCRIPT.md` | How to show it: from phones; on the hub desk | |
| `docs/EDGE_NODE.md` | A design note for an in-store computer that keeps working offline | Not built |
| `docs/history/` | The group project's plan, each member's guide, their report, the old single-server deploy | Kept for the record; not current |
| `CONTRIBUTING.md` | Branches, pull requests, checks, migrations | |
| `docker-compose.yml`, `Dockerfile`, `Makefile` | Running locally; the image that AWS runs | |

## 5. How it works

The longer versions are [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`DESIGN.md`](DESIGN.md). What a newcomer most
needs to know:

**One program, one database.** The services of the original design are modules in one process. A module may
call another module's `service.py`; only `inventory` writes stock. The database is PostgreSQL 16 with PostGIS,
and there is no other store. A two-second cache of each hub's availability lives in the process.

**Three rules the code keeps everywhere.**

- *A state change is one guarded update.* Claiming an order, taking a trip, confirming a hold: each is an
  `UPDATE ... WHERE state = <what it was>`, and zero rows changed means someone else got there first. Nothing reads
  a value, decides in Python and writes it back.
- *What must happen together happens in one transaction.* An order is written inside the payment that creates it;
  a trip is formed inside the packing that makes it due; an event is written with the change it describes.
- *Every stock movement is a ledger row.* The audit (`GET /v1/admin/stock-audit`) checks that the totals, the bins
  and the ledger agree, and every test that moves stock ends by checking it.

**An order's life.** Held for ten minutes → paid (the order is written and a pick job made) → picked, oldest batch
first (the order is priced by the batches picked) → packed (the sale is committed; stock leaves the shelf) →
pooled (on a trip; the door code appears) → out for delivery (every bag of the trip checked out) → delivered (the
right code) or delivery failed. A customer can cancel until the order is packed.

**Delivery.** A trip is formed at a hub when an agent is free and either four packed orders wait or the oldest has
waited ten minutes (half a minute on staging). It takes at most six: the longest-waiting order and its nearest
neighbours by compass direction. The stops are put in the shortest order by trying every order. Distances are
straight lines times 1.7, because no road service is wired in yet.

**Timed jobs** (`app/background.py`), all inside the app process:

| Job | Every | Does |
| --- | --- | --- |
| Holds | 30 s | Gives back the stock of holds that ran out |
| Expiry | 1 hour, and at start | Writes off batches past their use-by date |
| Stalled orders | 60 s | Returns to the queue an order nobody has scanned for 5 minutes |
| Trips | 30 s (10 s on staging) | Forms the trips that became due by waiting |
| Restocking | 15 minutes | Raises warehouse orders for packaged goods below their reorder point; never for farm produce |
| Demo farms | 30 minutes, and at start | Staging only: a lot for each produce item a hub is nearly out of |
| Demo hub | 10 s | Staging only: picks and packs an order nobody started within 45 s |

Because the jobs run inside the process, **only one copy of the app runs**; two would run every job twice.

## 6. The API, module by module

110 endpoints. The full, current list with every field is at `/docs` on any running copy. In outline:

| Module | What it answers | Main calls |
| --- | --- | --- |
| `accounts` | Who is signed in to the app | `POST /v1/auth/otp/request`, `/otp/verify`, `/refresh`, `/logout`; `GET` and `PATCH /v1/me` |
| `auth.py` | Staff logins | `POST /v1/auth/login` |
| `serviceability` | Cities, hubs, which hub serves an address, opening a hub, requests for delivery | `GET /v1/cities`, `/v1/stores`, `/v1/serviceability`; `POST /v1/service-requests`, `/v1/admin/stores` |
| `farms` | Produce items, farms, listings, the hub's intake | `GET /v1/produce-items`; `POST /v1/farms`, `/v1/listings`, `/v1/listings/{id}/intake` |
| `catalogue` | The shop's list for a hub | `GET /v1/stores/{id}/shop` |
| `inventory` | Availability, holds, adjustments, counts, the ledger, the audit | `POST /v1/reservations`, `/v1/reservations/{id}/confirm`; `DELETE /v1/reservations/{id}`; `GET /v1/admin/stock-audit` |
| `orders` | A customer's orders, and the bill for a held cart | `GET /v1/reservations/{id}/bill`; `POST /v1/orders`; `GET /v1/orders`; `POST /v1/orders/{id}/cancel` |
| `fulfilment` | Pick jobs, cancelling before packing, stalled orders, the desk's rider hand-over | `GET /v1/fulfilment-jobs`, `/v1/stores/{id}/attention` |
| `pickpack` | Claiming, scanning, empty shelves, substitutes, packing | `GET /v1/pickers/{id}/next-task`; `POST /v1/pick-tasks/{id}/scans`, `/v1/fulfilment-jobs/{id}/packed` |
| `delivery` | Agents, trips, hand-over, the hub's dispatch view | `GET /v1/agent`; `POST /v1/agent/duty`, `/v1/agent/trip/bags/{order}/load`, `/v1/agent/trip/stops/{order}/deliver` |
| `inbound` | Goods receipts, from the warehouse or a farm lot | `POST /v1/goods-receipts/open`, `/scans`, `/putaway`, `/close` |
| `replenishment` | Restocking packaged goods | `POST /v1/replenishment/run`; `GET /v1/transfer-orders` |
| `slotting`, `forecasting`, `assortment` | Which bin, how much will sell, what to stock | `GET /v1/slotting/plan`, `/v1/forecasting/compare`, `/v1/stores/{id}/assortment/recommendations` |
| `network_planning` | Demand on a map; where to open the next hub | `GET /v1/network-planning/heatmap`, `/suggestions` |
| `dashboard` | The ops dashboard and the live event feed | `GET /v1/stores/{id}/dashboard`; WebSocket `/v1/ws/events` |
| `monitoring.py` | The audit log of staff calls; Prometheus metrics | `GET /v1/audit`, `/metrics` |
| `main.py` | Health; demo tools | `GET /health`; `POST /v1/admin/demo-supply`, `/v1/admin/reset` |

Who may call what: the reads a shopper needs before signing in (serviceability, the shop, availability) are open
and rate-limited; the app's own calls need an app user's token of the right role; staff endpoints need a staff
token, and staff act only on their own hub; `/v1/admin/*` needs `admin`. Every staff call is in the audit log.

## 7. Settings

Every setting is an environment variable read in `app/config.py`, where each one is described. Staging's values
are in `infra/app.yml`. The ones a newcomer is most likely to need:

| Setting | Default | Staging | What it does |
| --- | --- | --- | --- |
| `DARKSTORE_DB` | a local `darkstore` database | from Secrets Manager | The database |
| `JWT_SECRET` | a public development value | a generated secret | Signs tokens; also the key the door codes are worked out from |
| `DEMO_PASSWORD` | `demo` | a generated secret | The staff password, used when the staff accounts are first created |
| `EMAIL_BACKEND` | `log` | `ses` | `log` writes sign-in codes to the server's log; `ses` sends them by email |
| `RATE_LIMIT_PER_SECOND`, `RATE_LIMIT_BURST` | 20, 40 | the same | Per address on the open endpoints; 0 turns it off |
| `RESERVATION_TTL_MINUTES` | 10 | the same | How long a cart is held while paying |
| `POOL_MIN_ORDERS`, `POOL_MAX_WAIT_MINUTES`, `TRIP_MAX_ORDERS` | 4, 10, 6 | 4, 0.5, 6 | When a trip leaves, and how many orders it takes |
| `RESCUE_WITHIN_DAYS`, `RESCUE_DISCOUNT` | 1, 0.3 | the same | Which batches are cheaper, and by how much |
| `DEMO_PRODUCE`, `DEMO_HUBS` | off | on | Add the produce catalogue and Bhilai's hubs to the demo data |
| `DEMO_SUPPLY` | off | on | Demo farms keep every hub stocked |
| `DEMO_AUTOPACK`, `DEMO_AUTOPACK_SECONDS` | off, 45 | on, 45 | The demo hub picks and packs orders nobody started |
| `AGENT_SELF_SIGNUP` | off | on | Anyone may sign in as a delivery agent |
| `OTP_MAX_PER_HOUR` | 5 | 15 | Sign-in codes an address may ask for in an hour |
| `BACKGROUND_JOBS` | on | on | Off in the tests |

Check `app/config.py` before relying on a default listed here; it is the source.

## 8. Environments

### On a laptop

[`README.md`](../README.md), "Run it yourself": PostgreSQL with PostGIS in Docker, then `uvicorn`. The staff
password is `demo`, and sign-in codes are written to the server's log. **The original developer's laptop cannot
run the backend or the tests:** Windows Application Control there blocks the compiled part of the `h3` library,
and it has no Docker. That is why the tests and the app build run on AWS.

### The development server

An EC2 machine tagged `Name=farm2home-dev-server` (`m7i.xlarge`: 4 vCPU, 16 GB) in Mumbai. It has no SSH key and no
open port: commands go through AWS Systems Manager (`aws ssm send-command`, or Session Manager in the console).
On it, in `/home/ec2-user/app`, are a clone of the repository with its Python environment, PostgreSQL with
PostGIS and Redis in Docker, Node 22, Playwright with Chromium, Java 17 and the Android SDK. It runs the end-to-end
recorder, the Android build and quick test runs.

It costs about 5.21 US dollars a day while it runs. Stop it when work pauses for days:

```powershell
$id = aws ec2 describe-instances --region ap-south-1 --filters Name=tag:Name,Values=farm2home-dev-server --query "Reservations[0].Instances[0].InstanceId" --output text
aws ec2 stop-instances --region ap-south-1 --instance-ids $id
```

Its PostgreSQL holds test data only. Do not drop and recreate its default database by hand: doing so once hid a
fault that a clean test machine would have caught.

### Staging on AWS

Region `ap-south-1` (Mumbai). Five CloudFormation stacks; every resource is tagged `Project=farm2home`:

| Stack | Holds |
| --- | --- |
| `farm2home-network` | The private network over two availability zones, and the NAT gateway |
| `farm2home-build` | The container registry and the image build |
| `farm2home-ci` | The test runner |
| `farm2home-data-staging` | PostgreSQL 16 on RDS (`db.t4g.medium`) with a standby in a second zone, 7 days of backups |
| `farm2home-app-staging` | The app on ECS Fargate (cluster `farm2home-staging`, service `api`; one container of 0.5 vCPU and 1 GB), the load balancer, the web firewall, the DNS name, the generated secrets |

Logs are in CloudWatch, log group `/farm2home/staging/api`, one JSON line per request. The database has no route
to the internet; only the app reaches it. **The AWS account also holds other projects. Touch nothing that is not
tagged `Project=farm2home`.**

Cost, from the AWS price list on 23 November, before data transfer and logs: staging about 7.70 US dollars a day,
half of it the database with its standby; the development server 5.21 a day while it runs. The project runs on
AWS credits.

## 9. Access: who holds what

| Thing | Held by | Where |
| --- | --- | --- |
| The repository `Galabavamsi/CSL559_CSD_Group_Project` | The owner, GitHub user Galabavamsi | Public |
| The AWS account | The owner, through the IAM user `vamsi` | `aws login`; the session lasts a few hours |
| The staff password for staging's hub pages | AWS Secrets Manager | `farm2home/staging/staff-password` |
| The token signing key | AWS Secrets Manager | Made by the app stack; never needs reading |
| The database login | AWS Secrets Manager, changed by RDS every 7 days | The app reads it at each new connection |
| Sending email | Amazon SES, from the project's domain, out of the sandbox | |
| The domain `farm2home.galabavamsi.com` | The owner's DNS, delegated to Route 53 | Certificates in ACM |
| The map tiles key | Amazon Location, `farm2home-map-tiles`: tiles only, ends 31 March 2027 | No code uses it yet |
| Built files | A private S3 bucket whose name contains the account id; files expire after 30 days | |
| The Android signing key | The debug key in Expo's generated Android project | The same for every Expo project; not secret |

To read the staff password:

```powershell
aws secretsmanager get-secret-value --region ap-south-1 --secret-id farm2home/staging/staff-password --query SecretString --output text
```

**Changing the staff password is not a one-step job.** The password is hashed into each staff account when the
accounts are first created, so changing the secret alone changes nothing: the accounts keep the old hash. A change
needs a migration or an admin call that rewrites the staff hashes, and neither exists yet. The current password
has been shared in a chat; treat it as known to anyone who saw that.

## 10. How to: the everyday tasks

Commands are for PowerShell on Windows, from the repository's folder, with the AWS CLI signed in (`aws login`) and
the GitHub CLI signed in (`gh auth login`). [`infra/README.md`](../infra/README.md) has more on the first four.

**Test a branch or a commit.** About five minutes on AWS. Prints the result and marks the commit on GitHub.

```powershell
infra\test.ps1 -Ref my-branch
```

**Deploy to staging.** About fifteen minutes. It tests the commit if it has not passed, builds the image, updates
the stack with the template of that commit, and waits for the new version to be healthy. Its last line, a health
check from the laptop, fails on a network that blocks the address; that alone does not mean the deploy failed.

```powershell
infra\deploy.ps1 -Env staging -Ref main
```

**Check staging afterwards**, from a machine that can reach it (the development server can):

```bash
bash infra/smoke.sh https://staging.farm2home.galabavamsi.com
```

**Roll back.** Deploy an older commit with the same command and `-Ref <commit>`. **This fails across a database
migration:** the older code does not know the newer migration and will not start, and ECS then keeps the newer
version running. After a migration, fix forward instead.

**Read the logs.**

```powershell
aws logs tail /farm2home/staging/api --region ap-south-1 --since 30m --format short
```

**Restart the app** without a new version (a fresh container from the same image):

```powershell
aws ecs update-service --region ap-south-1 --cluster farm2home-staging --service api --force-new-deployment
```

**Stock every hub now.** Staging does it every half hour; as `admin`, `POST /v1/admin/demo-supply` does it at once.

**Make a delivery agent's account.** As `admin`, `POST /v1/admin/agents` with an email address, a name and the
hub's number. On staging anyone may also sign up as an agent from the app.

**Reset the demo data.** `POST /v1/admin/reset` empties every table and loads the demo data again. It deletes every
order, account and listing on that copy. Do not run it against staging without having decided to.

**Build the Android app.** On the development server, which has the tools:

```bash
cd ~/app && git checkout main && git pull && API_URL=https://staging.farm2home.galabavamsi.com bash scripts/build_apk.sh
```

About eleven minutes the first time, a few minutes after that. The file is
`mobile/android/app/build/outputs/apk/release/app-release.apk`. To hand it out, attach it to a GitHub release
(`gh release create <tag> <file> --notes-file <notes>`). A phone with an earlier build takes it as an update.

**Run the whole flow as a check.** On the development server, `bash scripts/record_demo.sh` starts the backend on an
empty database, builds the app for the web, and drives nine passes through it in a real browser, from a farmer's
listing to the customer's door. About ten minutes. It also remakes the report's screenshots. It is the nearest
thing to an end-to-end test and has caught faults the unit tests could not.

**Rebuild the report.** Edit `docs/handbook/parts/*.html`, run `docs\handbook\build.ps1`, then read every page of
the PDF: several pages are full to the last line, and one more line moves a whole block.

**Other tools in `scripts/`.** `load_test.py` (a mix of calls; start the app with `RATE_LIMIT_PER_SECOND=0`),
`load_checkout.py` (many buyers racing for few units, then an audit), `compare_picking.py` and
`compare_slotting.py` (walking saved), `simulate_orders.py` (scripted pickers), `bench_availability.py` (the
cache), `generate_sales.py` and `generate_demand.py` (history for the dashboards and the map), `hub_intake.py` (take
in a farm lot from the command line). **`load_checkout.py` and `/v1/admin/reset` wipe data:** point them only at a
copy you mean to wipe.

## 11. Tests

- **800 tests in 63 files** under `tests/`, written with pytest. They run against a real PostgreSQL with PostGIS and
  **empty the database they are given** (`DARKSTORE_TEST_DB`) before each test, then load the demo data.
- `tests/conftest.py` provides a logged-in `client` (as `admin`), `client_as(role, hub)` for permission tests, a `db`
  session, `sku("Toned milk")` to find an item, and `assert_stock_is_consistent()`, which every test that moves
  stock calls at the end.
- **On AWS:** `infra\test.ps1 -Ref <branch>` runs them in CodeBuild on a fresh PostGIS, after checking that the
  migrations build exactly the tables in the models, syntax-checking the hub pages' scripts and type-checking the
  phone app. The result appears on the commit in GitHub as "tests (AWS CodeBuild)". Merge only on a pass.
- **They do not run by themselves on a push**, because the AWS connector for GitHub has not been given access to
  the repository. [`infra/README.md`](../infra/README.md) has the steps to switch that on.
- The phone app has no unit tests: `npx tsc --noEmit` in `mobile/` type-checks it, and the end-to-end recorder
  drives its web build.
- The hub pages have no unit tests: the recorder drives them, and the sign-in box was checked with three browsers
  at once on 24 November.

## 12. The phone app

[`mobile/README.md`](../mobile/README.md) is the full guide. In short:

- One app for customers, farmers and delivery agents; the account's role decides the home screen.
- `src/api/` has one interface with two implementations: the real API, when `EXPO_PUBLIC_API_URL` is set, and
  built-in demo data otherwise (any email, code 123456). Every screen goes through it.
- To try it while changing it: `npx expo start` in `mobile/`, then Expo Go on a phone. With the phone on a USB
  cable, `adb reverse tcp:8081 tcp:8081` lets it reach the laptop.
- The installable Android build comes from `scripts/build_apk.sh` (section 10). It is debug-signed: fine for
  installing by hand, not for a store.
- The 40 product photographs and their licences are in `mobile/assets/produce/` and `mobile/ASSETS.md`. Eleven are
  CC BY and need their credit shown in the app before any public release; the app does not show it yet.
- No iOS build has been made.

## 13. Known faults, limits and risks

In rough order of how much they matter for the demo.

| What | Effect | What to do |
| --- | --- | --- |
| Some networks block the staging address (the campus Wi-Fi, the developer's laptop network) | The app and the pages cannot connect | Use mobile data or a hotspot. A lasting fix is to serve the API from an address such filters already trust, for example a CloudFront one |
| No order has been placed from the installed app | An unknown fault could show on the day | Rehearse on phones first |
| The AWS sign-in on the laptop is a session of a few hours | A deploy or a test run stops with "Your session has expired", having changed nothing | Run `aws login` and start it again |
| The shop's read misses its target (130 ms against 100 ms at the 99th percentile, 23 November) | Slower under heavy load | Not a demo problem; measure again on the new code |
| Distances are straight lines times 1.7 | A trip's kilometres are an estimate; Bhilai's railway makes some real routes longer | Wire in Amazon Location's road times (design 1.2) |
| A door code locked by five wrong tries can only end as "not delivered" | The hub cannot release it | Build the release (design 4.7) |
| A bag that comes back is not handled | The order ends as "delivery failed", and its units are not put back | Build the hub's half of a failed delivery |
| The hub desk's "Rider collected the bag" works on any packed order | Pressed for a phone customer's order, it marks the bag handed over to a made-up rider; the delivery agent's "Bag checked" then fails and that trip is stuck | Use it only for orders paid at the desk. Fix: give made-up riders only to orders with no customer, and refuse the desk's hand-over for an order on a trip |
| The timed jobs' notes are not written to the log | "Trips formed" or "demo farms delivered" never appear in CloudWatch; only warnings and errors do, as plain text | Give the `darkstore` loggers a handler in `app/monitoring.py` |
| Rolling back across a migration fails | The older version will not start | Fix forward |
| Changing the staff password needs code | The secret and the stored hashes would disagree | Section 9 |
| One copy of the app | No second copy to take over; a restart takes about a minute | The load balancer, the standby database and rollback are ready for two copies once the timed jobs move out |
| Hub staff share one password per environment | No record of which person did what, beyond the role | Real staff accounts were decided against before the demo |
| `/metrics` answers anyone on staging | Counters and timings are public; no personal data or secrets | Restrict it to staff or to the private network |
| Sales statistics count a day from midnight UTC | A day of sales runs from 05:30 to 05:30 in India | Use-by dates and the rescue price already use India's date |
| The Android build is debug-signed | It cannot go to a store; a store build would need this one uninstalled | Make a release key when a store is wanted |
| Eleven photographs need credit in the app | Not yet shown | Add a credits screen before a public release |
| The report's video is from 23 November | It stops at Packed | Record again with `scripts/record_demo.sh` if a video is wanted |

## 14. What to do next

In order. Each item's design is in [`DESIGN.md`](DESIGN.md) at the section named.

1. **Rehearse on phones, on the venue's kind of network** ([`DEMO_ON_A_PHONE.md`](DEMO_ON_A_PHONE.md)). Two phones
   if possible. Fix only what the rehearsal finds.
2. **Decide about the blocked address** before 3 December (section 13, first row).
3. **The hub's half of a failed delivery**: put back or write off the bag that comes back, and release a locked
   code (design 4.7).
4. **The dispatch panel as a page** for the hub. The API exists: `GET /v1/stores/{id}/dispatch` (design 4.9).
5. **A map in the app**: the customer's pin and the agent's stops, with the tiles key that already exists (design
   1.2).
6. **Road times** for the order of stops and for a time of arrival (design 1.2 and 4.3).
7. **The simulated day**: the one measurement that would say whether pooling pays, and at what order rate (design 8).
8. **Hubs asking farms** for what they expect to sell (design 5).

## 15. Before the demo on 3 December

- Deploy nothing after the last rehearsal.
- An hour before: `GET /v1/stores/6/shop` lists about a dozen items. If not, call `POST /v1/admin/demo-supply` as
  admin.
- Have the staff password ready, and both phones signed in: one as a customer, one as a delivery agent on duty at
  BH-04 IIT Bhilai.
- To show the picker's page, have it open on hub 6 and press **Get next order** within 45 seconds of the payment;
  otherwise the server packs the order by itself.
- Sign in to AWS on the laptop that morning, in case something has to be restarted.
- Bring a mobile hotspot.

## 16. Loose ends at the moment of handover

- **Pull request 87** (a test from the group project's review of pull request 76) is still open. It was written
  against the code of 22 November. Run it through `infra\test.ps1` before merging it, or close it.
- **Branches on GitHub.** About ninety, most of them merged. Merged ones can be deleted without losing anything,
  since their commits are on `main`.
- **Tags** `v1.0` to `v1.6` and `darkstore-final` mark the group project's releases. Keep them.
- **A planned map in a code comment.** `mobile/src/features/location/LocationPicker.tsx` marks where a map picker
  plugs in; the map chosen is Amazon Location drawn with MapLibre (design 1.2), not Google Maps.
- **The release** `app-staging-2026-11-24` holds the Android app of 24 November.

## 17. History

| When | What |
| --- | --- |
| Until 22 November 2026 | The group project: a dark-store prototype by four students, one module area each. Their plan, guides and report are in [`history/`](history/README.md); the code as they left it is the tag `darkstore-final` |
| 23 November | The rebuild begins: cities and PostGIS, accounts by emailed code, farm supply, the phone app, staging on AWS, tests on AWS, Bhilai's hubs |
| 24 November | Orders on the server, the shop's batch facts and rescue price, maps decided, India's date, stocked shops, a hub at IIT Bhilai, delivery, an installable app, the report and this handover |

Each day's work, with what went wrong, is in [`journal/`](journal/README.md).

## 18. Words used here

| Word | Means |
| --- | --- |
| Hub | A small local micro-warehouse that serves the addresses around it |
| Zone | The addresses a hub serves, kept as H3 cells |
| H3 cell | A hexagon of a grid over the earth; at the resolution used (9), about a tenth of a square kilometre |
| Lot, listing | Produce a farmer brings: one item, so many kilograms, picked on one day |
| Batch | Units from one lot, or one warehouse delivery, with one use-by date; a farm lot's is written `L<listing>` |
| ATP | Available to promise: units on hand, less those held for carts, less a small safety margin |
| Hold | A cart's units set aside for ten minutes while the customer pays |
| FEFO | First expiry, first out: the batch with the earliest use-by date is picked first |
| Rescue price | 30% off the units of a batch in its last day |
| Pick job, pick task | The work of picking one paid order; one line of it, in one bin |
| Crate slot | The numbered place a packed bag waits in at the hub |
| Trip, stop | One agent's round from the hub with several orders; one order on it |
| Pooled | An order on a trip whose bags are still at the hub |
| Door code | The four digits a customer reads to the agent; worked out from the order's id and a secret, never stored |
| Staging | The copy on AWS that people use; there is no production |
| Demo farms, demo hub | Staging's stand-ins for farmers and pickers: the records are real, the people are simulated |
