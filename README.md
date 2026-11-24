# JustInTimeFarm2Home

Produce from farms to homes through small local hubs. A farmer lists a lot from a phone. The nearest hub with room
weighs it, grades it and packs it into units. A customer nearby buys from that hub's shelves. A delivery agent
carries several neighbours' orders in one trip and hands each over against a code the customer reads out.

It runs for two cities: **Bhilai** (tier 2, four hubs, one at IIT Bhilai) and **Bangalore** (tier 1, two hubs).

It is a *modular monolith*: one FastAPI app on PostgreSQL with PostGIS, a phone app for customers, farmers and
delivery agents, and plain web pages for the hub's staff. It grew out of a university group project (CSL559), a
dark-store prototype whose stock and picking code is still the base; that prototype as the group left it is the
tag `darkstore-final`.

## See it

A staging copy runs on AWS in Mumbai. It is a demo: orders are not real and no money moves.

| What | Where | Login |
| --- | --- | --- |
| The phone app, for Android | [Download from the releases page](https://github.com/Galabavamsi/CSL559_CSD_Group_Project/releases/tag/app-staging-2026-11-24) | An email address; a six-digit code is sent to it |
| Hub desk: customer, picker and store side by side, with a live feed of events | https://staging.farm2home.galabavamsi.com/ | Staff |
| Operations dashboard: problems first, each measure beside its target | https://staging.farm2home.galabavamsi.com/ops.html | Staff |
| Picker's phone screen | https://staging.farm2home.galabavamsi.com/picker.html | Staff |
| Receiver's intake screen: weigh, grade and put away a farm lot | https://staging.farm2home.galabavamsi.com/intake.html | Staff |
| Network map: zones, demand, requests for delivery, where to open a hub | https://staging.farm2home.galabavamsi.com/network.html?city=bhilai | Staff |
| The API, every call with a form to try it | https://staging.farm2home.galabavamsi.com/docs | None |

Staff logins are `picker<n>`, `packer<n>`, `receiver<n>` and `manager<n>` for hub number `n`, and the city-wide
`ops` and `admin`. Their password is not in this repository. Some networks block the staging address; mobile data
works.

To show it from phones alone, follow [`docs/DEMO_ON_A_PHONE.md`](docs/DEMO_ON_A_PHONE.md).

## Read about it

| Document | What it is |
| --- | --- |
| [The report](docs/handbook/JustInTimeFarm2Home-handbook.pdf) | System design, the screens in pictures, and what was measured |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Every decision with its reason, what else was considered, and what it costs |
| [`docs/journal/`](docs/journal/README.md) | One entry per piece of work: what was built, what went wrong, sources |
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | Where things stand, how to test, deploy and build, and what is known to be wrong |
| [`infra/README.md`](infra/README.md) | Running it on AWS |

## What works today

| Who | What they can do |
| --- | --- |
| **Farmer** (phone) | Register a farm where they stand. List a lot: the nearest hub with room is chosen and a morning drop slot given. See the hub's grade and the kilograms accepted and rejected |
| **Hub receiver** (web) | See the lots on their way with each farm's record. Weigh and grade a lot; it is packed into units. Put each portion in the bin the screen names; it is on sale from that moment |
| **Customer** (phone) | Choose where to deliver; the hub whose zone covers the address serves it, and an address nobody serves can ask for delivery. See only what that hub can deliver now, with each pack's grade, harvest date, use-by date and farm. Buy a batch in its last day 30% cheaper. Hold the whole cart for ten minutes and pay the hub's own bill. Follow the order to the door; cancel until it is packed |
| **Hub picker** (web) | Claim the next order, or three in one walk at busy times. Lines come in walking order, oldest batch first, and every unit is checked by barcode. An empty shelf moves the line to another bin or drops it. Packing commits the sale |
| **Delivery agent** (phone) | Choose a hub and go on duty. Be given a trip of packed orders, with the stops in the shortest round. Check each bag out by its crate slot. At the door, type the customer's four-digit code, or report why the order could not be handed over |
| **Hub and city staff** (web) | Watch stock, orders and events live. Restock from the warehouse, forecast, slot fast movers near the desk, count stock. See demand the hubs turned away and requests for delivery on a map, with suggested sites, and open a hub there in one step |

800 automated tests cover these, among them twenty buyers racing for the last unit, two customers shown the same
last cheap packs, and an order going from paid to delivered. What was measured, and one target that is missed, are
in the report.

**Not built:** a map in the app and the agent's position, a time of arrival, real payment, what the hub does with a
bag that comes back, and hubs asking farms for what they expect to sell. [`docs/DESIGN.md`](docs/DESIGN.md)
sections 4.10 and 6 say why.

## How it is put together

```
app/
  main.py            builds the app and plugs in every module
  config.py          every setting (hold time, trip rule, thresholds, the demo's stand-ins)
  models.py          all tables          migrations/ holds every change to them
  events.py          an in-process event bus with an outbox table; it stands in for Kafka
  clock.py           today's date where the hubs are (India), not where the server is
  demo_supply.py     staging only: demo farms deliver when a hub runs low
  demo_hub.py        staging only: an order no picker starts is picked and packed
  modules/           one package per service; each has service.py (the rules) and router.py (HTTP)
    accounts/        sign-in by emailed code, sessions, profiles
    serviceability/  cities, hubs, delivery zones as H3 cells, opening a hub, requests for delivery
    farms/           farms, listings, choosing a hub, weighing and grading
    inbound/         goods receipts, putaway        slotting/  which bin an item lives in
    inventory/       the only code that changes stock: holds, sales, counts, expiry, the ledger
    catalogue/       what a customer is told about a pack, and the rescue price
    orders/          a customer's order, its bill, its timeline
    fulfilment/      a pick job per paid order      pickpack/  claim, scan, empty shelf, pack
    delivery/        agents on duty, trips, bags checked out, the door code
    replenishment/   forecasting/   assortment/   network_planning/   dashboard/
mobile/              the phone app (Expo, React Native): one app, three roles
web/                 the hub's pages (plain HTML, CSS and JavaScript; no build step)
infra/               CloudFormation templates; scripts that test, deploy and smoke-test
scripts/             load tests, comparisons, the demo recorder, the app build
tests/               the test suite (pytest, against PostgreSQL with PostGIS)
docs/                design, journal, handover, the report
```

On AWS: the API in a container on ECS Fargate behind a load balancer with a web application firewall, PostgreSQL
16 on RDS with a standby in a second zone, images and tests built by CodeBuild. Five CloudFormation stacks, no
servers to log in to.

Three rules the code keeps:

- **One module changes stock.** Every other module asks `inventory`; every change is a row in a ledger, and an
  audit can compare the totals, the bins and the ledger at any time.
- **A state change is one guarded update.** Claiming an order, taking a trip, confirming a hold: each is an
  `UPDATE ... WHERE state = <what it was>`, so two people doing it at once cannot both succeed.
- **What must happen together happens in one transaction.** An order is written inside the payment that creates
  it; a trip is formed inside the packing that makes it due.

## Run it yourself

You need Python 3.10 or newer and PostgreSQL 16 with the PostGIS extension. With Docker, this starts a database on
`localhost:5432` (user, password and database are all `darkstore`, the app's default):

```bash
docker compose up -d postgres
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
DEMO_PRODUCE=on DEMO_HUBS=on DEMO_SUPPLY=on python -m uvicorn app.main:app --reload
```

The tables and demo data are created on first start. The three settings add the produce, Bhilai's hubs and the
demo farms that stock them; without them you get the dark-store prototype's two Bangalore stores and groceries.
For a database somewhere else, set `DARKSTORE_DB=postgresql://user:password@host:5432/database` first. Or, in one
command with Docker, `docker compose up --build`.

Then open http://localhost:8000 (the hub desk), `/ops.html`, `/picker.html`, `/intake.html`, `/network.html` and
`/docs`. Locally every staff account uses the password `demo`, and a sign-in code for the phone app is written to
the server's log when `EMAIL_BACKEND=log`.

**The phone app.** In `mobile/`:

```bash
npm install
npx expo start                                           # built-in demo data: any email, code 123456
EXPO_PUBLIC_API_URL=http://<this machine>:8000 npx expo start      # against your own API
```

**Tests.** `python -m pytest -q` with `DARKSTORE_TEST_DB` pointing at a PostGIS database (they wipe it). On AWS,
`infra\test.ps1 -Ref <branch>` runs them for any commit and marks it on GitHub.

**Other tools.** `scripts/load_test.py` (start the app with `RATE_LIMIT_PER_SECOND=0`), `scripts/compare_picking.py`
and `scripts/compare_slotting.py` (walking saved), `scripts/simulate_orders.py` (scripted pickers),
`scripts/generate_demand.py` (demand for the network map), `scripts/record_demo.sh` (the whole flow driven
through a real browser), `scripts/build_apk.sh` (the Android app). `docker compose --profile monitoring up` adds
Prometheus and Grafana; their configuration is in `monitoring/`.

## Logging in

Two kinds of login, never mixed:

- **People using the phone app** (customers, farmers, delivery agents) sign in with a six-digit code sent to
  their email address. There are no passwords. A delivery agent's account is made by an admin, unless
  `AGENT_SELF_SIGNUP` is on.
- **Hub and city staff** log in with a username and password and get a token that lasts 30 minutes. Staff may act
  only on their own hub: pickers and packers pick and pack, receivers and managers receive goods, managers adjust
  stock, `ops` can read every hub, and `/v1/admin/*` needs `admin`. Every call a logged-in staff member makes,
  refused or not, is kept in an audit log (`GET /v1/audit`).

Looking up whether an address is served, a hub's shop and holding a cart are open, and rate-limited: about 20
calls a second per address, then `429`. Outside local development set `JWT_SECRET` and `DEMO_PASSWORD`; the
built-in defaults are public.

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"manager1","password":"demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl localhost:8000/v1/stores/1/dashboard -H "Authorization: Bearer $TOKEN"
```

## The hub desk in five minutes

The page at `/` shows one order at three stations. It is the quickest way to see the stock rules.

1. On the **customer** station, press *Check delivery*, add 8 milk and 1 ice cream, then *Hold my items*.
   On the **ops** station the "Held" column changes at once; "On hand" does not.
2. Press *Pay now*. An `order.paid` event appears and "Waiting for a picker" becomes 1.
3. On the **picker** station press *Get next order*. The milk is split across two bins: the batch
   that expires first is picked first.
4. Try *Scan a wrong item* (rejected), then *Scan item* on each line, then *Mark packed*.
   Only now does "On hand" drop: the sale is committed at packing.
5. On the ops station press *Check what needs reordering*, then *Hub dispatches truck*, then
   *Receive truck*. The bread is back in stock and visible to the customer.

[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) is the full script for these screens, including the race for the
last ice cream.

## The services, and what each still simplifies

The first eleven rows are the dark-store prototype's services, as the group's high-level design (HLD) numbered
them. The rows after them were added for Farm2Home.

| Service | Module | What it does | Simplified for now |
| --- | --- | --- | --- |
| 1 Serviceability | `serviceability` | H3 cell to hub lookup, ETA, a zone that shrinks when the hub is busy; cities; opening a hub in one transaction, with its bins, zones and logins; requests for delivery where nobody serves | A cell has one hub, so a busy or closed hub's customers are not passed to a neighbour |
| 2 Assortment | `assortment` | List, add and drop items per hub; add, drop and shelf-room recommendations from 30 days of sales | Recommendations only: a manager applies them |
| 3 Inventory | `inventory` | What can be promised (on hand, less held, less a safety buffer); atomic holds that expire; oldest batch first, never an expired one; hourly write-off; blind cycle counts; a ledger and an audit of level, bins and ledger; every bin quantity changed by one guarded update | Saved idempotency keys are never cleaned up |
| 4 Fulfilment | `fulfilment` | A pick job per paid order; cancel until packed; stalled orders go back to the queue; order-to-pack times and fill rate | A packed order cannot be cancelled (that is a return, not built) |
| 5 Pick and pack | `pickpack` | Claim an order or a batch of three; scan unit by unit; empty-shelf fallback with partial finds; a substitute offered for dropped units; pack | A substitute is accepted on the customer's behalf at the desk |
| 6 Slotting | `slotting` | Fast movers nearest the packing desk; new deliveries go to an item's planned bin first | Within a temperature zone only; no rule for items bought together |
| 7 Forecasting | `forecasting` | Three models compared by measured error; reorder points with safety stock from forecast errors | Daily, not hourly; no weather or festivals |
| 8 Replenishment | `replenishment` | Packaged goods reordered from the warehouse in whole cases, within free shelf space | Farm produce is not reordered: it comes from farms. Run the timer in one app instance |
| 9 Inbound | `inbound` | Goods receipts in five steps; scanned units wait on the dock and are sellable the moment they are put away; damaged and short-dated units never enter stock | The desk receives a warehouse truck in one call; the step-by-step screen is for farm lots |
| 10 Network planning | `network_planning` | Orders, turned-away lookups and requests per H3 cell; suggested hub sites by greedy maximum coverage; a map | No-go cells are a list, not a zoning check |
| 11 Rider hand-off | `fulfilment/riders.py` | An order paid at the hub's desk gets a made-up rider and is handed over only against its own bag | Superseded for customers' orders by `delivery` |
| Accounts | `accounts` | Sign-in by emailed code with limits per address; sessions that renew and are ended if a spent token turns up again | No phone numbers or text messages |
| Farm supply | `farms` | Farms, listings, the nearest hub with room (PostGIS), drop slots, weighing and grading into units, a farm's rejection rate | A farmer sets any price; nothing matches supply to what the hub expects to sell |
| Catalogue | `catalogue` | The shop's list: for each item the batch picked next, its facts, and the rescue price for last-day units | One batch described per item |
| Orders | `orders` | An order written inside the payment; priced by the batches picked; the bill for a held cart; a price that rose is refused | Payment is a stand-in |
| Delivery | `delivery` | Trips formed when enough orders wait or the oldest has waited long enough; the shortest round; the agent free longest; bags checked out; a door code stored nowhere | Straight-line distances; no positions, map or arrival time; nothing handles a bag that comes back |
| Events | `events.py` | Events written to an outbox table in the same transaction as the change; a relay pushes them to a live feed per hub | No broker; the relay runs inside the app |
| Database | `db.py`, `cache.py`, `migrations/` | PostgreSQL with PostGIS; Alembic migrations applied at start-up; a two-second cache of a hub's availability | One app instance; each instance would have its own cache |

## More documents

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the code is organised and the rules everyone follows
- [`CONTRIBUTING.md`](CONTRIBUTING.md): branches, pull requests and the checks to run before pushing
- [`docs/DEPLOY_AWS.md`](docs/DEPLOY_AWS.md): the earlier, single-server way of running the prototype
- [`docs/EDGE_NODE.md`](docs/EDGE_NODE.md): design note for an in-store edge node, with an outage experiment
- [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md) and `docs/guide-member-*.md`: the group project's plan and each member's guide
