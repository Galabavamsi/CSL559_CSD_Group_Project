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
| `stock.changed` | inventory, pickpack | replenishment (raises `stock.low`) |
| `stock.low` | replenishment | nobody yet |
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
| Hourly forecasts, ML model | Daily moving average | Member 3 |
| Reservation timeout sweeper | Manual endpoint | Member 1 |
| Substitution and refund saga | Line is dropped, hold released | Member 2 |
| Batch picking at peak | One order per picker | Member 2 |
| Scan-item-then-bin putaway | One call receives and puts away | Member 3 |
| Store edge node | Not built | Out of scope; explain it in the report |
| Monitoring and KPIs | Basic dashboard numbers | Members 2, 3 and 4 |
