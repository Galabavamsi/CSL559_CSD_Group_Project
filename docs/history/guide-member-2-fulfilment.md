# Member 2 guide: Order fulfilment

**Your goal:** a paid order is packed fast and never gets stuck.
**You own:** `app/modules/fulfilment/`, `app/modules/pickpack/`, the job and task tables in
`app/models.py`, and the picker station in `web/`.
**HLD sections to know well:** 5 (services 4, 5 and 11), 6.1 Order to dispatch, 9.2 (saga, store overload).

Your code is the part with a clock on it. The HLD's headline target is yours: order accepted to
packed in **120 seconds or less** (90th percentile).

---

## 1. Your part in one minute

When a customer pays, Inventory publishes `order.paid`. From that moment the order is yours until a
rider walks out with the bag.

```
order.paid
    |
    v
 created  --claim-->  picking  --all lines scanned or reported-->  packed  --rider-->  handed_over
    \________________________________________________________________/
                  (cancelled: you will build this in task 2.3)
```

Each order is a `FulfilmentJob`. Each line to fetch is a `PickTask`:

```
pending  -->  picked        the right item was scanned
         -->  reallocated   shelf was empty; the line moved to another bin (a new pending task)
         -->  short         shelf was empty and no other stock; the line is dropped
```

## 2. Tour of your code

Read `fulfilment/service.py` then `pickpack/service.py` (about 20 minutes together).

| Function | Called by | What it does | Commits? |
| --- | --- | --- | --- |
| `fulfilment.on_order_paid` | `order.paid` event | Calls `create_job` | no (event handler) |
| `fulfilment.create_job` | above | Makes the job and one pick task per bin | no |
| `fulfilment.add_pick_tasks` | `create_job` | Asks Inventory which bins to use; records a `short` task if units cannot be found | no |
| `fulfilment.resequence` | several | Numbers tasks in walking order (`Bin.walk_seq`) | no |
| `fulfilment.refresh_store_load` | `create_job`, `pack` | Marks the store `busy` above 5 waiting orders | no |
| `fulfilment.handover` | `POST /v1/fulfilment-jobs/{id}/handover` | `packed -> handed_over` | yes |
| `pickpack.next_job` | `GET /v1/pickers/{id}/next-task` | Returns the picker's order, or claims the oldest waiting one | yes |
| `pickpack.scan` | `POST /v1/pick-tasks/{id}/scans` | Checks barcode and quantity; marks the line picked | yes |
| `pickpack.report_short` | `POST /v1/pick-tasks/{id}/short` | Empty shelf: correct the count, try another bin, else drop the line | yes |
| `pickpack.pack` | `POST /v1/fulfilment-jobs/{id}/packed` | Commits the sale for every picked line | yes |

### Try it by hand

```bash
# 1. Checkout and pay (8 milk from store 1)
curl -X POST localhost:8000/v1/reservations -H "Content-Type: application/json" \
  -d '{"order_id":"demo-10","store_id":1,"lines":[{"sku_id":1,"qty":8}]}'
curl -X POST localhost:8000/v1/reservations/<reservation_id>/confirm

# 2. Claim it as a picker. Note two tasks: 6 from batch M-OLD, 2 from M-NEW (oldest first)
curl "localhost:8000/v1/pickers/asha/next-task?store_id=1"

# 3. Scan the wrong thing, then the right thing (barcode and task ids are in the previous response)
curl -X POST localhost:8000/v1/pick-tasks/1/scans -H "Content-Type: application/json" -d '{"barcode":"000","qty":6}'
curl -X POST localhost:8000/v1/pick-tasks/1/scans -H "Content-Type: application/json" -d '{"barcode":"8900000000001","qty":6}'

# 4. Say the second bin is empty, then look at what the system did
curl -X POST localhost:8000/v1/pick-tasks/2/short

# 5. Pack
curl -X POST localhost:8000/v1/fulfilment-jobs/1/packed -H "Content-Type: application/json" -d '{"crate_slot":"S-01"}'
```

Then read `tests/test_order_flow.py`.

## 3. Ideas you need

**You never write stock.** To take units off the shelf you call `inventory.commit_sale`; to give a
hold back you call `inventory.unreserve`; to choose bins you call `inventory.allocate`. If you need
something Inventory does not offer, ask Member 1 for a function.

**The sale is committed at packing, not at scanning.** Until `pack` runs, nothing has left
`qty_on_hand`. So cancelling an order mid-pick only has to release holds (task 2.3).

**Claiming is a conditional UPDATE.** Two pickers pressing "next order" together must not get the
same order. `next_job` uses `UPDATE ... WHERE id = :job AND state = 'created'` and checks that one
row changed. Use the same pattern for every state change you add.

**The saga.** HLD 9.2 lists "Item missing on shelf" as a saga: *try another bin, offer a substitute,
else refund that line and post a stock adjustment*. `report_short` does the first and last steps
today. You will add the middle one.

**Why `spare` is calculated in `report_short`.** After an empty shelf is written off, the only
units that may cover the line are ones nobody else has on hold. Taking another customer's held
units would just move the problem to their order.

---

## 4. Your tasks

### Milestone 1

#### Task 2.1 (warm-up): Per-line timing and fulfilment metrics

*Why:* HLD 12 sets targets you cannot check yet: order-to-pack time ≤ 120 s (p90), fill rate ≥ 99%,
picker productivity ≥ 100 items per picker-hour.

*Steps*

1. In `app/models.py`, add `picked_at: Mapped[datetime | None]` to `PickTask`. Set it in
   `pickpack.scan` when a line becomes `picked`. Delete `darkstore.db`.
2. Add `fulfilment.metrics(db, store_id) -> dict` returning:

   | Key | Meaning |
   | --- | --- |
   | `orders_packed` | Jobs with state `packed` or `handed_over` |
   | `seconds_to_pack_p50`, `seconds_to_pack_p90` | From `created_at` to `packed_at` |
   | `seconds_claim_to_pack_p90` | From `picking_at` to `packed_at` (the part pickers control) |
   | `fill_rate` | Units picked ÷ units ordered, across all finished jobs |
   | `items_per_picker_hour` | Units picked ÷ total hours between `picking_at` and `packed_at` |

   For percentiles, sort the list and take the value at index `int(0.9 * (n - 1))`. That is good
   enough here; say which method you used in the report.
3. Expose it as `GET /v1/stores/{store_id}/fulfilment-metrics`.
4. Include `picked_at` in `job_view`.

*Done when*

- Test: three orders, one with a dropped line. `fill_rate` is below 1 and matches your arithmetic.
- Test: with no packed orders, the endpoint returns zeros or `null`s, not an error.

*Watch out:* units ordered = sum of the *reservation's* line quantities, not the sum of task
quantities. A re-allocated line appears as two tasks.

#### Task 2.2: Unit-by-unit scanning and partial finds

*Why:* a real picker scans each unit as it goes into the tote. The prototype needs the whole
quantity in one call, and "Not on shelf" is all-or-nothing even if 4 of 6 were there.

*Steps*

1. Add `scanned_qty: Mapped[int]` (default 0) to `PickTask`.
2. Change `scan(db, task_id, barcode, qty=1)`:
   - a wrong barcode still changes nothing;
   - add `qty` to `scanned_qty` with a conditional UPDATE
     (`WHERE id = :task AND scanned_qty + :qty <= qty`); zero rows changed means "too many";
   - when `scanned_qty == qty`, set status `picked`.
   Sending the full quantity in one call must still work, so existing tests and the demo keep passing.
3. Change `report_short` to accept an optional body `{"found": 4}`:
   - split the task: the found part becomes a `picked` task of 4;
   - run the existing empty-shelf logic for the remaining 2 only.
4. In `web/app.js`, show progress on each line ("4 of 6 scanned") and add a "Found only..." input
   next to *Not on shelf*.

*Done when*

- Test: six single-unit scans complete a 6-unit line; a seventh is rejected.
- Test: `found: 4` on a 6-unit line gives one picked task of 4, and 2 units re-allocated or dropped.
- `assert_stock_is_consistent()` passes after packing that order.

### Milestone 2

#### Task 2.3: Cancel after payment

*Why:* today a paid order cannot be cancelled at all (`inventory.release` answers
`already_paid`). Customers change their minds, and payments get reversed.

*What to build:* `POST /v1/fulfilment-jobs/{job_id}/cancel` with body `{"reason": "..."}`.

| Job state | Result |
| --- | --- |
| `created` or `picking` | Cancelled. Holds released. Nothing was ever taken off `qty_on_hand`, so there is nothing to put back in the books |
| `packed` or later | `409`: this is a *return*, which is out of scope. Say so in the report |

*Steps*

1. Add `fulfilment.cancel(db, job_id, reason)`:
   ```python
   changed = db.execute(
       update(FulfilmentJob)
       .where(FulfilmentJob.id == job_id, FulfilmentJob.state.in_(("created", "picking")))
       .values(state="cancelled")
   ).rowcount
   if changed == 0:
       raise DomainError(409, "too_late", "This order is already packed")
   ```
2. For every task that is `pending` or `picked`, call `inventory.unreserve(db, store_id, sku_id, qty)`
   and set the task status to `cancelled`. Tasks that are already `short` released their hold earlier;
   skip them. Tasks marked `reallocated` were replaced by new tasks; skip them too.
3. Set the reservation's status to `cancelled`.
4. Publish `fulfilment.state_changed` and a new `order.cancelled` event with `order_id` and `reason`
   (the Order service would refund from this).
5. Call `refresh_store_load` and commit.
6. In the picker station, if a scan comes back with `job_not_picking`, show "This order was
   cancelled. Put the items back on their shelves." Nothing needs to change in stock: the units
   never left the count.

*Done when*

- Test: cancel in `created`: ATP returns to its starting value.
- Test: cancel in `picking` with one line scanned and one pending: ATP returns to its starting value.
- Test: cancel after `packed` gives `409`.
- Test: two cancels at once release the holds once (same threading pattern as the race test).
- All end with `assert_stock_is_consistent()`.

#### Task 2.4: Substitutes for dropped lines

*Why:* HLD 6.1's fallback box says "next bin, else substitute or refund". The prototype goes
straight from "next bin" to "drop".

*Needs from Member 1:* `inventory.swap_line(db, reservation, old_sku_id, new_sku_id, qty)`, which
holds the substitute with the conditional UPDATE and updates the reservation line in one
transaction. Agree the signature with them at the start of the milestone.

*Steps*

1. Add `pickpack.find_substitute(db, store_id, sku_id, qty)`: same `category`, ATP of at least
   `qty`, nearest price. Return `None` if nothing fits.
2. In `report_short`, when units are dropped, include in the response
   `"substitute_offer": {"sku_id": ..., "name": ..., "price": ...}` (or `null`), and publish
   `order.line_dropped` with `order_id`, `sku_id`, `qty` and `refund_amount = qty * price`.
3. Add `POST /v1/fulfilment-jobs/{job_id}/substitutions` with body
   `{"dropped_sku_id": 14, "substitute_sku_id": 15, "qty": 1}`:
   - job must be `picking`;
   - call `inventory.swap_line` (if it raises `insufficient_stock`, pass the `409` through);
   - call `fulfilment.add_pick_tasks` for the substitute and `resequence`;
   - publish `order.line_substituted`.
4. Add an "Offer substitute" button to the picker station when an offer is present. In a real app
   the customer would approve it on their phone; in the demo the picker approves on their behalf.
   Write that assumption in the report.

*Done when*

- Test: the last ice cream is missing; the offer is "Frozen green peas 500 g"; accepting it creates
  a pending task for peas and lowers the peas ATP by 1.
- Test: with no stock in the category, the offer is `null` and `order.line_dropped` is in the event log.

### Milestone 3

#### Task 2.5: Stuck-order recovery

*Why:* "never gets stuck". If a picker claims an order and their handheld dies, the order sits in
`picking` forever and the customer waits.

*Steps*

1. Add `last_activity_at` to `FulfilmentJob`. Update it on claim, on every scan and on every
   shelf report.
2. Add `PICK_STALL_MINUTES` to `config.py` (try 5).
3. Add `fulfilment.recover_stalled(db) -> dict`:
   - a `picking` job with no activity for that long and **no** line picked yet goes back to
     `created` with `picker_id = None` (conditional UPDATE again), so another picker can claim it;
   - a stalled job with some lines already picked is left alone but returned in a `needs_attention`
     list, because the items are physically in someone's tote.
4. Ask Member 1 to call it from the background loop (their task 1.2), and expose
   `POST /v1/admin/recover-stalled` for the demo.
5. Add `GET /v1/stores/{store_id}/attention`: stalled jobs, plus `packed` jobs that have waited
   more than `RIDER_WAIT_MINUTES` for a rider. Member 4 shows this on the dashboard.

*Done when*

- Test: back-date `last_activity_at`; after `recover_stalled`, a different picker can claim the order.
- Test: a stalled job with a picked line is not released and appears under `needs_attention`.

#### Task 2.6: Batch picking at peak

*Why:* HLD 13.1 chose "single-order off-peak, batch picking at peak" and says why: "Batching raises
throughput at peak but adds wait when orders are few". Build it and measure whether that is true.

*Steps*

1. Add `BATCH_PICK_BACKLOG = 4` and `BATCH_SIZE = 3` to `config.py`.
2. Add `pickpack.next_batch(db, picker_id, store_id)`:
   - if the picker already has jobs in `picking`, return those;
   - count waiting orders; if fewer than `BATCH_PICK_BACKLOG`, claim one; otherwise claim up to `BATCH_SIZE`;
   - claim each with the conditional UPDATE from `next_job`.
3. Add `GET /v1/pickers/{picker_id}/next-batch?store_id=`. Response:
   ```json
   {"totes": {"A": "ORD-1", "B": "ORD-2", "C": "ORD-3"},
    "route": [{"tote": "B", "task_id": 7, "bin": "A-01-02", "sku": "...", "qty": 2}, ...]}
   ```
   `route` is every pending task from all the claimed jobs, sorted by `walk_seq`. One walk through
   the store serves three orders.
4. Scanning and packing stay per task and per job; no change needed there.
5. Show the tote letter on each line in the picker station.
6. **Measure it.** Write `scripts/compare_picking.py`: create 30 random paid orders; compute the
   total walking distance when picked one at a time versus in batches of 3. Use
   "distance of a route = highest `walk_seq` visited × 2" (walk out and back) as a simple model.
   Put the two numbers and the saving in the report.

*Done when*

- Test: with 5 waiting orders, `next-batch` returns 3; with 2 waiting, it returns 1.
- Test: the route is in non-decreasing `walk_seq` order across orders.
- Test: each order in a batch can be packed on its own.
- The comparison numbers are in the report.

### Milestone 4

#### Task 2.7: Rider handoff flow

*Why:* HLD service 11. Today `handover` is one unchecked call; a rider could take the wrong bag.

*Steps*

1. Add a `RiderAssignment` table: job_id, rider_id, status (`assigned`, `arrived`, `collected`), timestamps.
2. Subscribe to `order.ready_for_pickup` and create an assignment with a made-up rider id
   (this plays the part of the external rider system).
3. Add `POST /v1/riders/{rider_id}/arrive` with `{"order_id": ...}`: returns the crate slot to go to.
4. Change handover to take `{"rider_id": ..., "scanned_order_id": ...}` and reject it if the scanned
   bag is not this rider's order (`409 wrong_bag`).
5. Add `seconds_packed_to_handover_p90` to your metrics from task 2.1.

*Done when*

- Test: the wrong order id is rejected and the job stays `packed`.
- Test: the right one moves the job to `handed_over` and the assignment to `collected`.

#### Task 2.8: Picker phone screen and a 100-order timing run

*Why:* the picker station in the demo is built for a projector. A picker uses a phone.

*Steps*

1. Create `web/picker.html`: one column, large buttons, one line at a time ("Go to bin A-01-02,
   pick 2 × Basmati rice"), reusing the `api` helper from `app.js`.
2. Run the server with `--host 0.0.0.0` and open `http://<your-laptop-ip>:8000/picker.html` on a
   phone on the same Wi-Fi.
3. *Optional:* use the browser's `BarcodeDetector` (Chrome on Android) to scan with the camera.
   Print a sheet of barcodes from `GET /v1/skus` to scan.
4. Write `scripts/simulate_orders.py`: place 100 random paid orders and have a scripted "picker"
   claim, scan and pack them, sleeping 0.05 s per `walk_seq` step to imitate walking. Read
   `fulfilment-metrics` at the end.
5. Put the metrics table in the report beside the HLD targets, with one honest paragraph on what a
   simulation can and cannot tell you.

*Done when*

- A teammate can pick an order end to end on their phone.
- The simulation finishes with a clean stock audit and prints the metrics.

---

## 5. What others need from you

| Who | Needs | When |
| --- | --- | --- |
| Member 4 | `Store.status` to keep meaning `open` / `busy` / `closed` (serviceability reads it) | Always |
| Member 4 | `fulfilment.metrics` (2.1) and the attention list (2.5) for the dashboard | Milestones 1 and 3 |
| Member 4 | Events `fulfilment.state_changed`, `order.ready_for_pickup`, plus your new ones, with stable payload keys | Always |
| Member 1 | A heads-up before you need `swap_line` (2.4) and the background hook (2.5) | Start of Milestones 2 and 3 |
| Member 3 | The `not_found` ledger rows from `report_short`: they are a signal that a bin's count is unreliable | Always |
| Everyone | The shape of `job_view`: the demo screens read it. Add fields freely; do not rename them | Always |

## 6. What to show at the final demo

1. Oldest batch first: one milk order split across two bins.
2. A wrong scan rejected, then an empty shelf moved to another bin.
3. Cancel a paid order mid-pick and watch the "Held" column return to zero.
4. Six quick orders: the store turns busy, the ETA grows, and a batch of three is picked in one walk.
5. Your metrics next to the HLD targets.

## 7. If you have time left

- Let the customer approve or refuse a substitute (a pending state and a timeout).
- A separate packer role: pickers drop totes at a packing desk; packers scan the tote and pack.
- A weight check at packing: expected weight from the SKUs versus a number typed in.
