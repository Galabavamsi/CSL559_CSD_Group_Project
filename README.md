# Dark Store Prototype

A working prototype of the **micro-warehousing module** of a Blinkit-style quick-commerce app.
It follows the team's High-Level Design (HLD): one module per HLD service, one Inventory Service
that owns every stock change, and a checkout hold that makes overselling impossible.

It is a *modular monolith*: a single FastAPI app with SQLite, so anyone can run it in two minutes
with no setup. The module boundaries are the same as the HLD's service boundaries, so each part
can later be split out, moved to PostgreSQL, or put behind Kafka without a redesign.

## What works today

| Flow | What you can do |
| --- | --- |
| Find a store | Give a location, get the serving store and an ETA, or "not serviceable" |
| Shop | See only the items that store can deliver right now (available = on hand − held − a small safety buffer) |
| Checkout | Hold a whole cart for 10 minutes; the cart is held whole or not at all |
| Pay or cancel | Paying creates a pick job; cancelling or timing out gives the stock back |
| Pick | A picker claims the next order and gets lines in walking order, oldest batch first |
| Scan | Every line is checked by barcode; a wrong item is rejected |
| Empty shelf | The count is corrected, the line moves to another bin, or is dropped if none is left |
| Pack and hand off | Packing commits the sale; a rider handoff closes the order |
| Restock | Low items are reordered from the hub; a received truck is put away and sellable at once |
| Forecast | Reorder points are recalculated from a weekday-aware forecast; three models are compared by measured error (WAPE) |
| Watch | An ops dashboard with problems first and every HLD 12 KPI beside its target, plus a live event feed for each store |

Automated tests cover these flows and the permission rules, including twenty buyers racing for the last unit.

## Quick start

You need Python 3.10 or newer.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app (the database and demo data are created on first start)
python -m uvicorn app.main:app --reload
```

Then open:

- **http://localhost:8000** for the demo screens (customer, picker and store ops side by side)
- **http://localhost:8000/ops.html** for the ops dashboard (KPIs against HLD 12 targets, updated live)
- **http://localhost:8000/docs** for the interactive API reference
- **http://localhost:8000/metrics** for Prometheus metrics (alert rules in `docs/ARCHITECTURE.md`, section 9)

Run the tests with `python -m pytest -q`; `tests/test_end_to_end.py` walks the whole demo script through
the API with real logins. Reset the demo data with the button on the ops desk, or with `python -m app.seed`.

To load-test a running app (about 90% reads, 10% checkout holds, a fifth of them paid) and see p50 and p99
per endpoint against the HLD's 100 ms read target, run `python scripts/load_test.py --seconds 60 --reset`.

The demo data has one week of sales, too little to judge a forecast model: its accuracy shows as not
available. To try the models on two months of history, run `python scripts/generate_sales.py`, then call
`GET /v1/forecasting/compare?store_id=1` in `/docs`.

To see where a new store should go, run `python scripts/generate_demand.py`, then open
**http://localhost:8000/network.html**.

### With Docker

If you have Docker, one command builds and starts the app on http://localhost:8000
(the SQLite file is kept in a Docker volume, so data survives restarts):

```bash
docker compose up --build
```

To also start the PostgreSQL container that task 1.7 will move the app onto:

```bash
docker compose --profile postgres up --build
```

`docker compose down -v` stops everything and deletes the stored data.

## Logging in

Customer endpoints (serviceability, availability, reservations) are open. Everything else needs a
staff token. The demo data has `picker1`, `packer1`, `receiver1`, `manager1` (and `...2` for the
second store), plus city-wide `ops` and `admin`. They all use the password `demo`.

```bash
TOKEN=$(curl -s localhost:8000/v1/auth/login -H "Content-Type: application/json" \
  -d '{"username":"manager1","password":"demo"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl localhost:8000/v1/stores/1/dashboard -H "Authorization: Bearer $TOKEN"
```

In `/docs`, press *Authorize* and paste the token. The demo screens log in by themselves.
Tokens last 30 minutes. Outside local development set `JWT_SECRET` (signing key) and
`DEMO_PASSWORD` in the environment; the built-in defaults are public.

Staff may act only on their own store: pickers and packers pick and pack, receivers and managers
receive goods, managers adjust stock and run replenishment and forecasting, `ops` can read every
store, and `/v1/admin/*` needs `admin`.

## Five-minute tour

1. On the **customer** station, press *Check delivery*, add 8 milk and 1 ice cream, then *Hold my items*.
   On the **ops** station the "Held" column changes at once; "On hand" does not.
2. Press *Pay now*. An `order.paid` event appears and "Waiting for a picker" becomes 1.
3. On the **picker** station press *Get next order*. The milk is split across two bins: the batch
   that expires first is picked first.
4. Try *Scan a wrong item* (rejected), then *Scan item* on each line, then *Mark packed*.
   Only now does "On hand" drop: the sale is committed at packing.
5. On the ops station press *Check what needs reordering*, then *Hub dispatches truck*, then
   *Receive truck*. The bread is back in stock and visible to the customer.

`docs/DEMO_SCRIPT.md` has the full script for presenting, including the "last ice cream" race.

## Project layout

```
app/
  main.py            builds the app and plugs in every module
  config.py          every tunable number (hold time, lead time, thresholds)
  db.py              database engine and sessions
  models.py          all tables (HLD section 7.1)
  events.py          in-process event bus that stands in for Kafka
  seed.py            demo data
  modules/           one package per HLD service; each has service.py (logic) + router.py (HTTP)
    serviceability/  inventory/  fulfilment/  pickpack/  inbound/  replenishment/
    forecasting/     slotting/   assortment/  network_planning/    dashboard/
web/                 the demo screens (plain HTML, CSS and JavaScript; no build step)
scripts/             developer tools; generate_sales.py writes 60 days of seeded sales history
tests/               pytest suite
docs/                architecture notes, team plan and one guide per team member
```

## How the prototype maps to the HLD

| HLD service | Module | In the prototype | Simplified for now |
| --- | --- | --- | --- |
| 1 Serviceability | `serviceability` | H3 cell to store lookup, ETA, zone shrinks when the store is busy | Zones are rebuilt by hand (`POST /v1/admin/rebuild-zones`); a cell has one store, so a busy or closed store's customers are not passed to a neighbour |
| 2 Assortment | `assortment` | List and add SKUs per store | No demand-based recommendations |
| 3 Inventory | `inventory` | ATP with a per-SKU safety buffer (`PUT /v1/stores/{id}/stock-settings/{sku_id}`), atomic holds, confirm, release (race-proof), automatic expiry sweep every `SWEEP_INTERVAL_SECONDS`, adjustments, ledger, FEFO allocation | No cache |
| 4 Fulfilment Orchestrator | `fulfilment` | Job per paid order, pick tasks, state machine, store busy flag | No cancellation after payment |
| 5 Pick & Pack | `pickpack` | Claim next order, scan check, empty-shelf fallback, pack | One order per picker; no substitutes |
| 6 Slotting | `slotting` | Suggest a bin in the right temperature zone | No velocity or affinity rules |
| 7 Forecasting | `forecasting` | Moving average, weekday average and exponential smoothing compared by WAPE backtest; reorder points with safety stock from forecast errors | Daily, not hourly; no weather or festivals |
| 8 Replenishment | `replenishment` | Reorder-point check, transfer orders, in-transit stock, supply KPIs (`GET /v1/stores/{id}/supply-kpis`) | Run by hand; no bin-capacity cap |
| 9 Inbound | `inbound` | Goods receipt against a transfer order, shortfall report, putaway | One call does receive and putaway |
| 10 Network Planning | `network_planning` | Orders and turned-away lookups per H3 cell, greedy max-coverage site suggestions, no-go cells, map at `/network.html` | Demand is generated (`scripts/generate_demand.py`); no-go cells are a config list, not a zoning check |
| 11 Rider Handoff | `fulfilment` | `order.ready_for_pickup` event and a handover call | No real rider system |
| Kafka | `events.py` | Events written to an outbox table; a relay pushes them to sinks (a WebSocket feed per store) and marks them published; lag shown on the dashboard | No broker yet; the relay runs inside the app |
| PostgreSQL + Redis | `db.py` | SQLite | One file, no sharding, no cache |
| Auth, gateway | `auth.py` | Login with a signed token; roles and own-store checks on every staff endpoint | No gateway or mutual TLS; customer endpoints are open; demo accounts share one password |

Every "simplified" cell is a task in one of the member guides.

## Team documents

- [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md): who owns what, milestones, and how the four parts fit together
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the code is organised and the rules everyone follows
- [`docs/guide-member-1-inventory.md`](docs/guide-member-1-inventory.md): Inventory and stock integrity
- [`docs/guide-member-2-fulfilment.md`](docs/guide-member-2-fulfilment.md): Order fulfilment (pick, pack, handoff)
- [`docs/guide-member-3-supply.md`](docs/guide-member-3-supply.md): Supply (forecasting, replenishment, inbound, slotting)
- [`docs/guide-member-4-platform.md`](docs/guide-member-4-platform.md): Platform, store network and screens
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md): the script for presenting the prototype
- [`CONTRIBUTING.md`](CONTRIBUTING.md): branches, pull requests and the checks to run before pushing
