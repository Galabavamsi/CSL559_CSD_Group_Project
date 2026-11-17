# Architecture of the prototype

Read this once before your first task. It explains how the code is organised, how one order
travels through it, and the rules that keep four people's work from colliding.

## 1. The shape: a modular monolith

The HLD describes eleven services. The prototype runs them all in **one process**, as eleven
Python packages under `app/modules/`. HLD section 13.1 recommends exactly this for a student
build: "a student prototype can start as a modular monolith with the same boundaries".

```
                 browser (web/)            other callers (curl, tests)
                        \                       /
                         v                     v
                   +-------------------------------+
                   |  FastAPI app  (app/main.py)   |   <- stands in for the API gateway
                   +-------------------------------+
                                  |
        +-------------+-----------+-----------+----------------+
        v             v                       v                v
  serviceability   fulfilment --> pickpack   inbound      replenishment
                        \            |          |          forecasting
                         \           |          |          slotting / assortment
                          v          v          v
                        +------------------------+
                        |  inventory/service.py  |   <- the only code that writes stock
                        +------------------------+
                                  |
                 +----------------+-----------------+
                 v                                  v
        SQLite (app/models.py)             event_log table (app/events.py)
        stands in for PostgreSQL           stands in for Kafka
```

Each module has two files:

| File | Contains | Rule |
| --- | --- | --- |
| `service.py` | Business logic as plain functions: `reserve(db, ...)`, `pack(db, ...)` | First argument is always the database session. No HTTP types here. |
| `router.py` | HTTP endpoints | Parse input, call **one** service function, shape the output. No business rules here. |

Because logic lives in `service.py`, modules can call each other directly
(`inventory.allocate(...)`) and tests can call logic without going through HTTP.

## 2. One order, followed through the code

| Step | HTTP call | Function | What happens in the database |
| --- | --- | --- | --- |
| Find store | `GET /v1/serviceability` | `serviceability.check` | Read only |
| Browse | `GET /v1/stores/{id}/availability` | `inventory.availability` | Read only. ATP = `qty_on_hand − qty_reserved` |
| Checkout | `POST /v1/reservations` | `inventory.reserve` | One conditional `UPDATE` per line raises `qty_reserved`; a `Reservation` row is written. All lines succeed or the transaction rolls back |
| Pay | `POST /v1/reservations/{id}/confirm` | `inventory.confirm` | Reservation becomes `confirmed`; publishes `order.paid` |
| (event) | | `fulfilment.on_order_paid` → `create_job` | A `FulfilmentJob` and its `PickTask` rows are written. `inventory.allocate` chooses bins, oldest batch first |
| Claim | `GET /v1/pickers/{id}/next-task` | `pickpack.next_job` | Conditional `UPDATE` moves the job `created → picking` for exactly one picker |
| Scan | `POST /v1/pick-tasks/{id}/scans` | `pickpack.scan` | Task becomes `picked` if the barcode and quantity match |
| Empty shelf | `POST /v1/pick-tasks/{id}/short` | `pickpack.report_short` | Count corrected (`not_found` ledger row); line re-allocated to another bin, or dropped and its hold released |
| Pack | `POST /v1/fulfilment-jobs/{id}/packed` | `pickpack.pack` → `inventory.commit_sale` | `StockItem.qty`, `qty_on_hand` and `qty_reserved` all drop; `sale` ledger rows; publishes `order.ready_for_pickup` |
| Handoff | `POST /v1/fulfilment-jobs/{id}/handover` | `fulfilment.handover` | Job becomes `handed_over` |

Two moments matter most:

- **Checkout** is where overselling is prevented. Stock is *held*, not removed.
- **Packing** is where the sale is *committed*. Until then a cancel or a failed payment only has to
  release a hold; no stock count ever has to be "put back".

## 3. Stock is stored twice, on purpose

| Table | One row per | Used for |
| --- | --- | --- |
| `StockLevel` | store + SKU | Totals: `qty_on_hand`, `qty_reserved`, reorder point. Fast ATP reads and the atomic hold |
| `StockItem` | store + SKU + bin + batch | Where the units physically are and when they expire. Pick paths, FEFO, putaway |
| `StockLedger` | every movement | Append-only history: who moved what, when and why |

The HLD puts `qty_reserved` on every `StockItem` row. The prototype holds stock at the store + SKU
level instead, because a hold then needs exactly one row to change, which keeps the no-overselling
`UPDATE` simple. Bins are chosen later, when the pick tasks are created.

**The three records must always agree:**

```
StockLevel.qty_on_hand  ==  sum of StockItem.qty  ==  sum of StockLedger.delta
0  <=  StockLevel.qty_reserved  <=  StockLevel.qty_on_hand
```

`assert_stock_is_consistent()` in `tests/conftest.py` checks this. Call it at the end of every
test that moves stock. If it fails, some code changed one record without the others.

## 4. Events

`events.publish(db, type, store_id, payload)` writes a row to `event_log` **inside the caller's
transaction** and then calls any subscribed handlers in the same transaction. If the stock change
rolls back, so does the event. This is the "transactional outbox" from HLD 9.2, minus the relay.

| Event | Published by | Handled by (today) |
| --- | --- | --- |
| `stock.changed` | inventory, pickpack | replenishment (raises `stock.low`); inventory counts (opens a count of the bin when the cause is `not_found`) |
| `stock.low` | replenishment | nobody yet |
| `count.needs_approval` | inventory counts (difference above `COUNT_AUTO_APPROVE_VALUE`) | nobody yet (live feed shows it) |
| `item.near_expiry` | inventory (hourly job, once per batch per day) | nobody yet (live feed shows it) |
| `order.paid` | inventory | fulfilment (creates the job) |
| `fulfilment.state_changed` | fulfilment, pickpack | nobody yet |
| `order.ready_for_pickup` | pickpack | nobody yet (the rider system would) |
| `store.status_changed` | fulfilment | nobody yet |
| `transfer_order.created` / `.dispatched` | replenishment | nobody yet (the hub WMS would) |
| `goods.received` | inbound | nobody yet |
| `forecast.updated` | forecasting | nobody yet |

To react to an event, subscribe in your module's `service.py`:

```python
from ... import events

@events.subscribe("stock.low")
def on_stock_low(db, store_id, payload):
    ...   # runs inside the publisher's transaction; do not commit here
```

Handlers must not call `db.commit()`: the code that published the event commits once, at the end.

## 5. Transactions: who commits?

- Functions called straight from a router (`reserve`, `confirm`, `pack`, `receive_goods`, ...) commit.
- Helper functions that are one step of a bigger operation (`inventory.receive`, `commit_sale`,
  `unreserve`, `write_off_missing`, `fulfilment.create_job`) do **not** commit. Their docstrings say so.
- Event handlers never commit.

If you are unsure, read the docstring. If it does not say, fix the docstring in your pull request.

## 6. Concurrency rules used in the code

Two places must be safe when many requests arrive at once. Both use the same trick: an `UPDATE`
with the check in its `WHERE` clause, then look at how many rows changed.

```python
# inventory.reserve: hold stock only if enough is free right now
UPDATE stock_levels SET qty_reserved = qty_reserved + :qty
WHERE store_id = :store AND sku_id = :sku AND qty_on_hand - qty_reserved >= :qty
# rowcount == 0  ->  not enough stock

# pickpack.next_job: give an order to exactly one picker
UPDATE fulfilment_jobs SET state = 'picking', picker_id = :me
WHERE id = :job AND state = 'created'
# rowcount == 0  ->  another picker got there first
```

Never write "read the value, check it in Python, then write it back" for stock or job state.
Two requests can both read the old value and both pass the check.

## 7. Errors

Raise `DomainError(status, code, message, details)` from service code. `main.py` turns it into:

```json
{"error": {"code": "insufficient_stock", "message": "Not enough stock for one or more items",
           "details": {"lines": [{"sku_id": 14, "requested": 2, "available": 1}]}}}
```

Use `409` when the request is valid but the current state forbids it (not enough stock, wrong job
state), `422` for bad input, and `404` via `errors.not_found(...)`.

## 8. Where the prototype differs from the HLD

| HLD | Prototype | Who closes the gap |
| --- | --- | --- |
| PostgreSQL sharded by `store_id` | One SQLite file | Member 1 (PostgreSQL), sharding stays a design-only topic |
| Redis ATP cache | Reads hit the database | Member 1 |
| Kafka | `event_log` table + in-process handlers | Member 4 |
| API gateway, JWT, roles | Open endpoints | Member 4 |
| H3 delivery zones | Radius around each store | Member 4 |
| Hourly forecasts, ML model | Daily forecast: three simple models compared by WAPE, weekday average in use | Member 3 |
| Reservation timeout sweeper | Manual endpoint | Member 1 |
| Substitution and refund saga | Line is dropped, hold released | Member 2 |
| Batch picking at peak | One order per picker | Member 2 |
| Scan-item-then-bin putaway | One call receives and puts away | Member 3 |
| Store edge node | Not built | Out of scope; explain it in the report |
| Monitoring and KPIs | Prometheus metrics at `GET /metrics`, request ids and JSON logs (section 9); no Prometheus server or Grafana in the prototype | Members 2, 3 and 4 |

## 9. Monitoring

`GET /metrics` is a Prometheus scrape target (`app/metrics.py` defines the metrics, `app/monitoring.py`
serves them):

| Metric | Type | Labels | Where it is counted |
| --- | --- | --- | --- |
| `http_request_duration_seconds` | histogram | method, route template, status | middleware, every request |
| `reservations_total` | counter | result: `held`, `insufficient_stock` | `inventory.reserve` |
| `events_published_total` | counter | event type | `events.publish` |
| `scans_total` | counter | result: `match`, `mismatch` | `pickpack.scan` |
| `holds_in_progress` | gauge | | read from the database at scrape time |
| `outbox_lag_seconds` | gauge | | read at scrape time; same number as the dashboard tile |
| `store_seconds_since_last_event` | gauge | store id | read at scrape time |

The latency histogram is labelled with the route template (`/v1/stores/{store_id}/availability`), not the
raw path, so the number of series does not grow with the number of stores; an HTTP method outside the usual
seven is labelled `other`. The counters go up when the code runs, before the transaction commits, so a
rolled-back request still counts: fine for rates and alerts, not for exact totals. Set `METRICS_TOKEN` and
`/metrics` answers only `Authorization: Bearer <METRICS_TOKEN>`; with it unset (local development) it is open.

Every request gets an id: the caller's `X-Request-ID` if it is at most 64 letters, digits, `.`, `_` or `-`,
otherwise a new one. It is returned in the `X-Request-ID` response header and written on every log line
made while the request is handled. The app logs one JSON object per line to stderr, including one line per
request with its method, route, status and time in milliseconds.

### Alert rules (HLD 12)

| Alert | Metric | Fires when (PromQL) |
| --- | --- | --- |
| Spike in failed reservations | `reservations_total` | more than 20% of holds fail over 5 minutes: `sum(rate(reservations_total{result="insufficient_stock"}[5m])) / sum(rate(reservations_total[5m])) > 0.2` |
| Event lag | `outbox_lag_seconds` | above 30 s for 1 minute: `outbox_lag_seconds > 30` |
| Slow reads | `http_request_duration_seconds` | read p99 above the 100 ms target: `histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{method="GET"}[5m]))) > 0.1` |
| Cache and database disagree | Member 1's stock audit (task 1.8) | any mismatch; not wired up until the audit exists |
| Store offline | `store_seconds_since_last_event` | above 15 minutes during opening hours: `store_seconds_since_last_event > 900` |

The thresholds (20%, 15 minutes) are first guesses to tune with real traffic. Prometheus and Grafana
themselves are not part of the prototype; the rules above are what you would load into Prometheus.
