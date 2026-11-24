# Architecture

Read this before changing the code. It says how the code is organised, how a request travels through it, and the
rules every module keeps. Why each rule is the way it is, and what else was considered, is in
[`DESIGN.md`](DESIGN.md). What was built each day, and what went wrong, is in [`journal/`](journal/README.md).

## 1. The shape: a modular monolith

One FastAPI process holds every service, each as a Python package under `app/modules/`. They share one PostgreSQL
16 database with PostGIS. The same process serves the hub's web pages (`web/`), and the phone app (`mobile/`) calls
the same API.

```text
   phone app (mobile/)        hub pages (web/)        scripts, tests
            \                        |                      /
             v                       v                     v
     +------------------------------------------------------------+
     |  app/main.py: middleware (request id, log line, audit,      |
     |  rate limit), logins (app/auth.py), one router per module   |
     +------------------------------------------------------------+
          |            |            |            |            |
      accounts   serviceability   farms ...    orders     delivery
          \            \            |            /            /
           v            v           v           v            v
     +------------------------------------------------------------+
     |  app/modules/inventory/service.py: the only code that       |
     |  changes stock quantities                                    |
     +------------------------------------------------------------+
                                    |
         PostgreSQL 16 with PostGIS: the tables in app/models.py,
         the event_log table as an outbox (app/events.py)
```

Each module has a `service.py` and a `router.py`:

| File | Holds | Rule |
| --- | --- | --- |
| `service.py` | The rules, as plain functions: `reserve(db, ...)`, `pack(db, ...)` | The first argument is the database session. No HTTP types |
| `router.py` | The HTTP endpoints | Parse the input, check who is calling, call one service function, shape the answer. No business rules |

Because the rules are plain functions, modules call each other directly and tests can call the rules without HTTP.

### The modules

| Package | What it does | Its tables |
| --- | --- | --- |
| `accounts` | People who use the phone app (customers, farmers, agents): six-digit codes sent by email, sessions with refresh tokens, profiles | `users`, `login_codes`, `refresh_tokens` |
| `serviceability` | Cities and hubs; which hub serves an H3 cell, and how fast; opening a hub with its bins, zone and logins (`open_store`); requests for delivery where nobody serves | `cities`, `stores`, `bins`, `store_zones`, `serviceability_misses`, `service_requests` |
| `farms` | Produce items, farms, listings; the nearest hub with shelves and room (PostGIS); drop slots; weighing and grading a lot (`intake`), which opens a goods receipt | `produce_items`, `farms`, `listings`, `quality_checks` |
| `inbound` | Goods receipts in five steps (open, scan onto the dock, putaway tasks, put away, close), and the older one-call receipt (`receive_goods`) | `goods_receipts`, `goods_receipt_lines` |
| `slotting` | Which bin an item lives in: fast movers nearest the packing desk, new deliveries to the planned bin | none of its own |
| `inventory` | Holds, allocation oldest batch first, the sale at packing, receipts, moves, adjustments, expiry, the ledger and the audit. `counts.py`: blind cycle counts and their approval | `stock_levels`, `stock_items`, `stock_ledger`, `reservations`, `reservation_lines`, `cycle_counts`, `cycle_count_lines`, `idempotency_records` |
| `catalogue` | The shop's list: availability plus the batch a customer would get next, and the rescue price for a batch in its last day | none |
| `orders` | A signed-in customer's order, written inside the payment, its lines priced by batch, its bill and its timeline | `orders`, `order_lines`, `order_events` |
| `fulfilment` | A pick job per paid order; cancel until packed; stalled orders back to the queue; the hub's measures. `riders.py`: the made-up rider of the dark-store prototype, and handing a bag to a delivery agent | `fulfilment_jobs`, `pick_tasks`, `rider_assignments` |
| `pickpack` | Claim an order or a batch of three; scan unit by unit; empty shelf; substitutes; pack | the job tables, with `fulfilment` |
| `delivery` | Agents on duty, trips, the order of the stops, bags checked out, the door code, failed hand-overs, the dispatch view | `agent_profiles`, `trips`, `trip_stops` |
| `replenishment` | Reorders from the warehouse in whole cases within free shelf space; transfer orders; supply measures | `transfer_orders`, `transfer_order_lines` |
| `forecasting` | Daily demand from the ledger, three models compared by their error, reorder points | `forecasts` |
| `assortment` | Which items a hub carries; recommendations to add or drop | a `stock_levels` row is "carried" |
| `network_planning` | Orders, turned-away lookups and requests per H3 cell; suggested hub sites | none |
| `dashboard` | Read-only numbers for the hub desk and the ops page; the live event feed over a WebSocket | none |

### The files beside the modules

| File | What it does |
| --- | --- |
| `app/main.py` | Builds the app: middleware, every router, `web/` mounted last. Starts the event relay and the timed jobs. Also `GET /health`, `POST /v1/admin/reset` and `POST /v1/admin/demo-supply` |
| `app/config.py` | Every setting, read from the environment once, with a comment saying what it does |
| `app/db.py` | The engine and sessions (`get_db`); `init_db` brings the tables up to date at start-up. With `DB_SECRET_ARN` set it reads the database login from Secrets Manager whenever it opens a connection |
| `app/models.py` | Every table |
| `app/auth.py` | Staff login (`POST /v1/auth/login`), tokens, and the dependencies `current_staff`, `require_role`, `check_store`, `current_user` and `require_user_role` |
| `app/events.py` | The event bus: `publish`, `subscribe`, `add_sink`, and the relay that sends events on (section 5) |
| `app/clock.py` | `today()`: the date in India. Anything that asks what day it is asks here |
| `app/cache.py` | A two-second cache of a hub's availability list, dropped whenever a stock level is written |
| `app/idempotency.py` | `run_once`: a write sent again with the same `Idempotency-Key` gets the first answer back |
| `app/rate_limit.py` | Middleware: about 20 calls a second per address, then `429`, on the paths in `OPEN_PATHS`: logins, address lookups, the lists of hubs, cities and items, availability and holds. The shop's list and the produce items are open but not on that list |
| `app/monitoring.py` | Middleware: a request id, the timing, one JSON log line per request, and the audit log. `GET /metrics` and `GET /v1/audit` |
| `app/metrics.py` | The Prometheus metrics (section 9) |
| `app/background.py` | Every timed job, in one place (section 8) |
| `app/seed.py` | The demo data: Bangalore's two hubs with groceries; with `DEMO_PRODUCE` and `DEMO_HUBS`, the produce and Bhilai's four hubs. `reset` empties the database and seeds it again |
| `app/demo_supply.py` | With `DEMO_SUPPLY` (staging only): demo farms bring a lot to any hub nearly out of a produce item, through the ordinary intake |
| `app/demo_hub.py` | With `DEMO_AUTOPACK` (staging only): an order no picker has started after `DEMO_AUTOPACK_SECONDS` is claimed, scanned and packed with the picker's own functions |
| `app/email.py` | Sending email: `log` writes the message to the log (a laptop, the tests); `ses` sends it through Amazon SES |
| `app/errors.py` | `DomainError` and `not_found` (section 7) |
| `app/ids.py` | `Id` and `PathId`: an id outside the database's integer range is refused with `422` |

## 2. Who may call whom

A module calls the modules below it in its row, through their `service.py` functions. Nothing calls upwards: a
module that needs to know what happened above it listens for an event instead (`orders` follows the pick job that
way, because `fulfilment` must not know about orders).

| Module | Calls |
| --- | --- |
| `delivery` | `orders`, `fulfilment` (`riders.py`), `serviceability` |
| `orders` | `catalogue`, `fulfilment`, `inventory` |
| `pickpack` | `fulfilment`, `inventory` |
| `fulfilment` | `inventory` |
| `farms` | `inbound`, `serviceability` |
| `inbound` | `slotting`, `inventory` |
| `assortment` | `replenishment`, `forecasting`, `inventory` |
| `replenishment`, `slotting` | `forecasting`, `inventory` |
| `forecasting`, `catalogue` | `inventory` |
| `network_planning` | `serviceability` |
| `dashboard` | `inventory`, `serviceability`; and the measures of `fulfilment`, `inventory.counts` and `replenishment`, looked up by name when the ops page asks, so one that fails does not break the page |
| `accounts`, `serviceability`, `inventory` | No other module |

Above the modules: `app/background.py` calls `delivery`, `fulfilment`, `inventory`, `replenishment`, `demo_hub` and
`demo_supply`; `demo_supply` calls `farms`, `inbound` and `inventory`; `demo_hub` calls `pickpack`; `seed` calls
`serviceability`, and the router that opens a hub calls `seed` for the hub's logins.

A module writes its own tables. Reading another module's tables in a query is done where it saves a round of calls
(the catalogue joins batches to farms; the dashboard counts jobs). The exceptions to writing: `fulfilment` creates
the job tables and `pickpack` moves them through picking and packing; `delivery.add_agent` and `demo_supply` add
`users` rows directly; `assortment` adds and removes an empty `stock_levels` row, and `replenishment` and
`forecasting` change its reorder settings, never its quantities.

## 3. One order, from a farm to a door

| Step | Call | Function | What changes |
| --- | --- | --- | --- |
| A farmer lists a lot | `POST /v1/listings` (farmer) | `farms.create_listing` | A listing at the nearest hub with shelves and room, with a morning drop slot; `listing.created` |
| The hub weighs and grades it | `POST /v1/listings/{listing_id}/intake` (receiver) | `farms.intake`, then `inbound.open_receipt` and `inbound.scan` | A quality check; the accepted kilograms packed into whole units, on the dock of a new goods receipt; `listing.received` |
| Putaway | `GET .../putaway-tasks`, `POST .../putaway`, `POST .../close` under `/v1/goods-receipts/{receipt_id}` | `inbound.put_away`, then `inventory.receive` | Units in a bin, on sale at once; a ledger row; `stock.changed`; at close, `goods.received` |
| Where to deliver | `GET /v1/serviceability` | `serviceability.check` | Nothing; a point no hub serves is saved as a miss for planning |
| The shop | `GET /v1/stores/{store_id}/shop` | `catalogue.shop` | Nothing |
| Hold the cart | `POST /v1/reservations` | `inventory.reserve` | One guarded `UPDATE` per line raises `qty_reserved`; every line or none; a ten-minute hold |
| The bill | `GET /v1/reservations/{reservation_id}/bill` | `orders.bill` | Nothing |
| Pay | `POST /v1/orders` (customer) | `orders.place`, then `inventory.confirm` | The hold is confirmed and `order.paid` published. In the same transaction `orders.on_order_paid` writes the order, `fulfilment.on_order_paid` creates the pick job (`inventory.allocate`, oldest batch first), and `orders.on_job_state` prices each unit by its batch and refuses a bill dearer than the one shown (`409 price_changed`) |
| Claim | `GET /v1/pickers/{picker_id}/next-batch` | `pickpack.next_batch` | Guarded `UPDATE` of the job from `created` to `picking` |
| Scan | `POST /v1/pick-tasks/{task_id}/scans` | `pickpack.scan` | Barcode checked; a guarded `UPDATE` adds to `scanned_qty` |
| Empty shelf | `POST /v1/pick-tasks/{task_id}/short` | `pickpack.report_short` | The count is corrected and the line moves to another bin, or is dropped: `order.line_dropped` takes it off the order, and a substitute may be offered |
| Pack | `POST /v1/fulfilment-jobs/{job_id}/packed` | `pickpack.pack`, then `inventory.commit_sale` | Stock leaves the books (`sale` ledger rows). In the same transaction the order becomes `packed` and `delivery.on_job_state` forms a trip if one is due |
| A trip | Packing, an agent coming on duty or free, or the timer | `delivery.form_trips` | The agent free longest is claimed by a guarded `UPDATE`; the orders become `pooled`; `trip.formed`. The customer now sees the door code |
| Bags out | `POST /v1/agent/trip/bags/{order_id}/load` (agent) | `delivery.load_bag`, then `riders.give_to_agent` | The job is `handed_over`; with every bag loaded the trip is out and its orders `out_for_delivery`; `trip.left` |
| At the door | `POST /v1/agent/trip/stops/{order_id}/deliver`, or `.../fail` | `delivery.deliver` or `delivery.fail` | The code is checked against `orders.door_code`; the order `delivered` (or `delivery_failed`); after the last stop `trip.done` and the agent is free |
| Cancel, until packed | `POST /v1/orders/{order_id}/cancel` | `orders.cancel`, then `fulfilment.cancel` | Guarded `UPDATE` of the job to `cancelled`; `inventory.unreserve` gives the held units back; the order follows |

Two moments matter most. **Holding** is where overselling is prevented: stock is set aside, not removed.
**Packing** is where the sale is committed. Until then a cancel or a failed payment only releases a hold, and no
count is ever "put back".

The hub desk page pays with `POST /v1/reservations/{reservation_id}/confirm` and no customer, so it makes a pick job
but no order. Its packed bag goes to a made-up rider (`riders.assign_rider`), who collects it with
`POST /v1/riders/{rider_id}/arrive` and `POST /v1/fulfilment-jobs/{job_id}/handover`. Every packed job is given a
made-up rider, a customer's too; for those, the agent's `load_bag` takes the bag over.

### What a request passes through

1. `monitoring.observe` gives it an id, times it and, at the end, writes its log line and (for a staff caller) the
   audit row. Inside it, `rate_limit.limit` refuses a client over its rate on an open endpoint.
2. The router's dependencies: a database session (`get_db`) and the caller (`current_staff`, `require_role`,
   `current_user` or `require_user_role`). `check_store` refuses staff acting on another hub. Ids are checked by
   type (`Id`, `PathId`).
3. One service function. It changes rows with guarded updates, publishes events (whose handlers run at once, in the
   same transaction) and commits once.
4. A `DomainError` raised anywhere becomes the JSON error of section 7.
5. Within a fraction of a second the relay sends the new events to the WebSocket feed of the hub's pages.

## 4. Stock: whole units, recorded three ways

| Table | One row per | Used for |
| --- | --- | --- |
| `stock_levels` | hub and item | Totals: `qty_on_hand`, `qty_reserved`, `safety_buffer`, reorder point. Fast reads, and the one row a hold changes |
| `stock_items` | hub, item, bin and batch | Where the units are and when they expire. Pick paths, oldest batch first, putaway |
| `stock_ledger` | every movement | Append-only history: who moved what, when and why |

What can be promised is `qty_on_hand - qty_reserved - safety_buffer`. A hold is kept per hub and item, not per bin,
so it needs exactly one row to change; bins are chosen when the pick tasks are made. Stock is counted in whole
units: a farmer deals in kilograms, and intake packs them into units (a 500 g pack), with what does not fill a unit
recorded as trim.

**Only `app/modules/inventory/service.py` changes stock quantities.** Every change writes a ledger row, and the
three records must always agree:

```text
stock_levels.qty_on_hand  ==  sum of stock_items.qty  ==  sum of stock_ledger.delta
0  <=  stock_levels.qty_reserved  <=  stock_levels.qty_on_hand
```

`inventory.audit` checks this; `GET /v1/admin/stock-audit` runs it on a live database, and
`assert_stock_is_consistent()` in `tests/conftest.py` runs it at the end of a test. If a new kind of stock change is
needed, add a function to `inventory/service.py`; do not write the stock tables from anywhere else.

## 5. Events

`events.publish(db, type, store_id, payload)` writes a row to `event_log` **inside the caller's transaction**, then
calls every handler subscribed to that type, in the same transaction. If the change rolls back, so does the event,
and so does whatever the handlers did. This is a transactional outbox. A relay (`events.run_relay`, every
`RELAY_INTERVAL_SECONDS`) sends unsent events, oldest first, to every sink and marks them sent. The one sink today
is the WebSocket feed (`dashboard.service.push_to_listeners`). Delivery to sinks is at least once.

| Event | Published by | Handled by |
| --- | --- | --- |
| `stock.changed` | `inventory`, `pickpack`, `fulfilment` (cancel), `inventory.counts` | `replenishment` (raises `stock.low`); `inventory.counts` (opens a count of a bin found empty, and while it is open writes off held units given back in that bin) |
| `stock.low` | `replenishment` | nobody |
| `order.paid` | `inventory.confirm` | `orders.on_order_paid` (first: writes the order when a signed-in customer is paying); `fulfilment.on_order_paid` (creates the pick job) |
| `fulfilment.state_changed` | `fulfilment`, `pickpack`, `fulfilment.riders` | `orders.on_job_state` (prices the lines when the job is created; marks the order packed or cancelled); `delivery.on_job_state` (forms a trip when a job is packed) |
| `order.line_dropped` | `fulfilment` (job created short), `pickpack` (empty shelf) | `orders.on_line_dropped` (takes the units off the order) |
| `order.line_substituted` | `pickpack` (substitute accepted) | `orders.on_line_substituted` (adds the substitute) |
| `order.ready_for_pickup` | `pickpack.pack` | `fulfilment.riders.assign_rider` (a made-up rider) |
| `order.cancelled`, `rider.assigned`, `store.status_changed` | `fulfilment`, `fulfilment.riders` | nobody (the live feed shows them) |
| `trip.formed`, `trip.left`, `trip.done` | `delivery` | nobody |
| `listing.created`, `listing.received` | `farms` | nobody |
| `goods.received` | `inbound` | nobody |
| `transfer_order.created`, `transfer_order.dispatched`, `replenishment.capped`, `reordering.changed` | `replenishment` | nobody |
| `forecast.updated` | `forecasting` | nobody |
| `count.needs_approval` | `inventory.counts` (a difference worth more than `COUNT_AUTO_APPROVE_VALUE`) | nobody |
| `item.near_expiry` | `inventory` (the expiry job, once per batch per day) | nobody |
| `store.opened` | `serviceability.open_store` | nobody |

To react to an event, subscribe in your module's `service.py`:

```python
from ... import events

@events.subscribe("stock.low")
def on_stock_low(db, store_id, payload):
    ...   # runs inside the publisher's transaction; never commit here
```

- A handler never calls `db.commit()`. The code that published the event commits once, at the end.
- Handlers run in the order their modules were imported. `subscribe(type, first=True)` puts one ahead of the
  others, for the rare handler whose record the rest build on (`orders.on_order_paid`).
- A handler is registered when its module is imported. A module whose router `main.py` does not import must be
  imported by something that is, or its handlers never run.
- A sink may get an event twice. Remember the event id if that matters.

## 6. Transactions, guarded updates and retries

**Who commits.**

- A function called straight from a router commits (`reserve`, `confirm`, `pack`, `place`, `load_bag`, ...).
- A write that takes an `Idempotency-Key` is called with `commit=False`, and `run_once` commits it together with the
  saved answer. These are: stock adjustments, every goods receipt step, creating a listing, intake, opening a hub,
  and applying a slotting plan.
- A function that is one step of a larger operation does not commit, and its docstring says so:
  `inventory.receive`, `commit_sale`, `unreserve`, `write_off_missing`, `write_off_unpromised`,
  `fulfilment.create_job`, `orders.move`, `delivery.form_trips(commit=False)`.
- Event handlers never commit.

If a docstring does not say whether the function commits, fix the docstring in your pull request.

**What must happen together shares one transaction.** An order is written inside the hold's confirmation, with its
pick job. Packing commits the sale, marks the order packed and forms the trip. An event is written with the change it
describes. A hub is opened with its bins, zones and logins. An idempotent write is saved with its answer.

**Every state change is one guarded update.** The check is in the `WHERE` clause, and the code looks at how many rows
changed:

```sql
-- inventory.reserve: hold stock only if enough is free right now
UPDATE stock_levels SET qty_reserved = qty_reserved + :qty
WHERE store_id = :store AND sku_id = :sku AND qty_on_hand - qty_reserved - safety_buffer >= :qty
-- no row changed: not enough stock

-- pickpack: give an order to exactly one picker
UPDATE fulfilment_jobs SET state = 'picking', picker_id = :me
WHERE id = :job AND state = 'created'
-- no row changed: another picker got there first

-- orders.move: an order moves only from the status it is expected to be in
UPDATE orders SET status = 'packed' WHERE order_id = :id AND status IN ('confirmed')
-- no row changed: the event came twice, or the order has moved on
```

Never read a value, check it in Python and write it back for stock, a job, an order, a trip or an agent. Two
requests can both read the old value and both pass the check. Where no single row can carry the guard, a PostgreSQL
advisory lock does: one trip-forming per hub at a time, one demo top-up at a time, one app instance migrating at a
time. A statement blocked by another transaction for 15 seconds fails instead of hanging (`app/db.py`).

**Retries.** A client that may send a write twice (a phone on a bad connection, a receiver tapping again) sends an
`Idempotency-Key` header. The first request does the write and saves its answer in the same transaction; a repeat
gets the saved answer; a key reused for a different request is refused (`422 idempotency_key_reused`). Saved keys
are never cleaned up.

## 7. Errors, dates and settings

Service code raises `DomainError(status, code, message, details)`. `main.py` turns it into:

```json
{"error": {"code": "insufficient_stock", "message": "Not enough stock for one or more items",
           "details": {"lines": [{"sku_id": 14, "requested": 2, "available": 1}]}}}
```

Use `409` when the request is valid but the current state forbids it (not enough stock, wrong job state, too late
to cancel), `422` for bad input, `404` through `errors.not_found(...)`, and `401` or `403` for logins and roles.
Someone else's order answers `404`, not `403`: as far as the caller knows, it does not exist.

**Dates.** Every stored time is UTC without a time zone (`models.utcnow()`). A calendar date (a use-by date, a
harvest date, "today") is India's: ask `clock.today()`, which adds `LOCAL_UTC_OFFSET_MINUTES`. Sales statistics
(forecasting, assortment, the day's sales) still count a day from midnight UTC; `DESIGN.md` section 3.4 says why.

**Settings.** Every number that could change is in `app/config.py`, read from the environment. The demo's stand-ins
(`DEMO_PRODUCE`, `DEMO_HUBS`, `DEMO_SUPPLY`, `DEMO_AUTOPACK`, `AGENT_SELF_SIGNUP`) are off unless turned on; staging
turns them on in `infra/app.yml`.

## 8. Timed jobs

The timed jobs run inside the API process, each in its own loop (`app/background.py`), with their database work on a
thread. A run that fails is logged and tried again next time. `BACKGROUND_JOBS=off` stops them all (the tests do);
the event relay is started separately and still runs.

| Job | Every | Does | Runs when |
| --- | --- | --- | --- |
| Release expired holds | `SWEEP_INTERVAL_SECONDS` (30) | `inventory.sweep_expired` | Always |
| Expiry | `EXPIRY_INTERVAL_SECONDS` (3600), and once at start | Writes off expired batches; flags batches near expiry | Always |
| Stalled orders | `STALL_CHECK_SECONDS` (60) | `fulfilment.recover_stalled`: an idle order goes back to the queue | Always |
| Trips | `DELIVERY_CHECK_SECONDS` (30; 10 on staging) | `delivery.form_all`: a trip that is due because an order has waited long enough | Always |
| Replenishment | `REPLENISHMENT_INTERVAL_MINUTES` (15) | `replenishment.run_all` for every open hub | Above 0 |
| Demo farms | `DEMO_SUPPLY_INTERVAL_MINUTES` (30), and once at start | `demo_supply.top_up` | `DEMO_SUPPLY` on |
| Demo hub | `DEMO_AUTOPACK_CHECK_SECONDS` (10) | `demo_hub.pack_waiting` | `DEMO_AUTOPACK` on |

Only one copy of the API runs, and `DesiredCount` in `infra/app.yml` stays 1, because these jobs and the live feed
are in the process. Most jobs would be safe twice (guarded updates, advisory locks); replenishment would not, since
its lock is per process.

## 9. Monitoring

`GET /metrics` is a Prometheus scrape target (`app/metrics.py` defines the metrics, `app/monitoring.py` serves them):

| Metric | Type | Labels | Where it is counted |
| --- | --- | --- | --- |
| `http_request_duration_seconds` | histogram | method, route template, status | middleware, every request |
| `reservations_total` | counter | result: `held`, `insufficient_stock` | `inventory.reserve` |
| `events_published_total` | counter | event type | `events.publish` |
| `scans_total` | counter | result: `match`, `mismatch` | `pickpack.scan` |
| `atp_cache_lookups_total` | counter | result: `hit`, `miss` | `inventory.availability`, whole-hub list only |
| `holds_in_progress` | gauge | | read from the database at scrape time |
| `outbox_lag_seconds` | gauge | | read at scrape time; the same number as the dashboard tile |
| `store_seconds_since_last_event` | gauge | store id | read at scrape time |

The latency histogram is labelled with the route template (`/v1/stores/{store_id}/availability`), not the raw path,
so the number of series does not grow with the number of hubs; an HTTP method outside the usual seven is labelled
`other`. The counters go up when the code runs, before the transaction commits, so a rolled-back request still
counts: fine for rates and alerts, not for exact totals. With `METRICS_TOKEN` set, `/metrics` answers only
`Authorization: Bearer <METRICS_TOKEN>`; unset, it answers anyone. Staging does not set it yet
([`HANDOVER.md`](HANDOVER.md) lists this as a known fault).

Every request gets an id: the caller's `X-Request-ID` if it is at most 64 letters, digits, `.`, `_` or `-`, otherwise
a new one. It is returned in the `X-Request-ID` header and written on every log line made while the request is
handled. The app's own loggers (named `app...`) write one JSON object per line to stderr, including one line per
request with its method, route, status and time in milliseconds.

The same middleware keeps the audit log. `auth.current_staff` puts the decoded token on the request; after the
response, the middleware writes an `audit_entries` row: who (username, role, hub), what (method, route template,
path with query string), the status they got and the request id. Refusals are kept too, so a picker trying another
hub shows up as a `403`. Calls by app users, and calls with no valid token, are only in the request log. The row is
written in its own session after the handler has finished, and a failed write is logged without failing the call.
WebSocket connections do not pass through the HTTP middleware and are not audited.

### Alert rules

| Alert | Metric | Fires when (PromQL) |
| --- | --- | --- |
| Spike in failed holds | `reservations_total` | more than 20% of holds fail over 5 minutes: `sum(rate(reservations_total{result="insufficient_stock"}[5m])) / sum(rate(reservations_total[5m])) > 0.2` |
| Event lag | `outbox_lag_seconds` | above 30 s for 1 minute: `outbox_lag_seconds > 30` |
| Slow reads | `http_request_duration_seconds` | read p99 above the 100 ms target: `histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{method="GET"}[5m]))) > 0.1` |
| Hub offline | `store_seconds_since_last_event` | above 15 minutes: `store_seconds_since_last_event > 900` |

The rules are in `monitoring/alerts.yml`. Prometheus evaluates them when started with
`docker compose --profile monitoring up --build`; with no Alertmanager they show on Prometheus's *Alerts* page and
nowhere else. Nothing on AWS scrapes `/metrics`: there the logs go to CloudWatch
([`../infra/README.md`](../infra/README.md)). The thresholds are first guesses. "Hub offline" ignores opening hours.
There is no rule for the stock audit: it is a call (`GET /v1/admin/stock-audit`), not a metric.

Grafana, in the same profile, opens on a dashboard (`monitoring/grafana/dashboards/darkstore.json`): requests per
second and read p99 per route against the 100 ms target, holds by result, `429`s and `5xx`s, events by type, scans by
result, outbox lag and each hub's silence. `docs/img/grafana-dashboard.png` is a screenshot from a load test of the
group project's SQLite build, on 18 November; the measurements of the current build are in the report
(`docs/handbook/`).

## 10. Tests

The tests (`tests/`, pytest) run against PostgreSQL with PostGIS: the database `DARKSTORE_TEST_DB` names, or
`postgresql://darkstore:darkstore@localhost:5432/darkstore`. **Every table in it is emptied before each test.**
On AWS they run with `infra\test.ps1` (see [`../CONTRIBUTING.md`](../CONTRIBUTING.md)).

`tests/conftest.py` sets, before the app is imported, `DARKSTORE_DB` to the test database, `BACKGROUND_JOBS=off`
(no timed jobs: a test calls the job's function itself, such as `inventory.sweep_expired` or `delivery.form_all`)
and `RATE_LIMIT_PER_SECOND=0`. It provides:

| Name | What it gives |
| --- | --- |
| `fresh_data` | Runs for every test: `seed.reset()`, the plain demo data (two Bangalore hubs, 16 grocery items, no produce, no Bhilai hubs) |
| `client` | A `TestClient` logged in as `admin`, for tests of rules rather than permissions |
| `client_as(role, store_id)` | A client logged in with that role at that hub; leave `store_id` out for `ops` |
| `db` | A database session |
| `sku(prefix)` | An item's id by the start of its name: `sku("Toned milk")` |
| `atp(client, store_id, sku_id)` | What can be promised of one item |
| `place_paid_order(client, order_id, store_id, lines)` | Hold and pay, as the hub desk does |
| `assert_stock_is_consistent()` | The stock audit of section 4; call it at the end of any test that moves stock |
| `plant_sales(db, sales, store_id)` | A sales history of your choosing, for forecasting and slotting |

Tests that need produce, Bhilai's hubs or app users set them up themselves: `seed.add_produce(db)`,
`seed.add_demo_hubs(db)`, and a `users` row with a token from `auth.make_user_token` (the `as_user` fixture in
`tests/test_farm_supply.py` is the pattern). Sign-in codes are read from `app.email.outbox`. Tests that need an
empty database (`tests/test_migrations.py`, the comparison scripts) make a throwaway one with `scripts/scratch.py`,
so the database login needs the right to create databases.

One file per feature or fault, named after it: `test_orders.py`, `test_delivery.py`, `test_inventory_races.py`,
`test_empty_shelf_writeoff.py`. `tests/test_end_to_end.py` walks the hub desk's script through the API with real
logins and ends with the stock audit. `tests/test_migrations.py` checks that the migrations build exactly the tables
in `models.py`.

## 11. Adding an endpoint or a module

**An endpoint.**

1. Put the rule in the module's `service.py` as a function taking `db` first, with a docstring that says what it
   does, what it refuses and whether it commits.
2. Add the route to the module's `router.py`: a Pydantic model for the body, `Id` or `PathId` for ids, a `summary`,
   and the caller as a dependency (`require_role(...)` and `check_store` for staff; `require_user_role(...)` for app
   users). Call the one service function.
3. A write a client may send twice takes an `Idempotency-Key` header and goes through `run_once`.
4. A new endpoint that needs no login and reads the database belongs in `OPEN_PATHS` in `app/rate_limit.py`.
5. A test: the rule, the refusals, the permissions, and `assert_stock_is_consistent()` if stock moves.
6. Do not change an existing endpoint's request or answer: the phone app (`mobile/src/api/http.ts`) and the hub
   pages read them. Adding a field is fine.

**A module.**

1. `app/modules/<name>/` with an empty `__init__.py`, a `service.py` and a `router.py` that defines
   `router = APIRouter(tags=["<name>"])`.
2. Import the router in `app/main.py` and add it to the tuple of routers there.
3. Its tables in `app/models.py`, and a migration for them ([`../CONTRIBUTING.md`](../CONTRIBUTING.md) says how).
4. Call only modules below it (section 2). To follow something above it, subscribe to an event; to tell others,
   publish one, and add it to the table in section 5.
5. A timed job goes in `app/background.py`, in `loops()`.
6. Add the module to the tables in section 1 and in `README.md`, and write the decisions it embodies in `DESIGN.md`.

## 12. Where this came from

The project began as a university group project (CSL559): a dark-store prototype built by four students, each owning
a set of modules. The first eleven services follow the group's high-level design (HLD); its section numbers, and the
members' task numbers ("task 2.6"), still appear in code comments. The HLD itself is not in this repository. The
plan, each member's guide and their report are in [`history/`](history/README.md); the code as the group left it is
the tag `darkstore-final`. It was then rebuilt by one person into JustInTimeFarm2Home, which added `accounts`,
`farms`, `catalogue`, `orders`, `delivery`, cities, PostGIS and the phone app.

Where the code still differs from the HLD:

| HLD | Today |
| --- | --- |
| PostgreSQL sharded by hub | One PostgreSQL 16 database with PostGIS; sharding stays a design |
| Redis cache of what can be promised | An in-process cache per app instance (`ATP_CACHE_SECONDS`); holds never read it |
| Kafka | The outbox table, in-process handlers, and a relay inside the app that feeds the WebSocket |
| An API gateway | Logins, roles and own-hub checks in the app; a rate limit in the app; on AWS a load balancer and a web firewall in front |
| Hourly forecasts | Daily; three models compared by their error, the weekday average in use |
| A rider system | Made-up riders for the hub desk's orders; customers' orders go with delivery agents on trips |
| A computer in each store | Not built; a design note and an outage experiment in [`EDGE_NODE.md`](EDGE_NODE.md) |
| Monitoring and alerts | `/metrics`, request ids and JSON logs; Prometheus and Grafana in Docker Compose only; no Alertmanager |
