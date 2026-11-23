# Orders on the server, the shop's batch facts, and a design written down

*24 November 2026. With no earlier design to follow for what is left, one was written with a reason for each
decision. Its first two pieces are built: a customer's order is a record on the server, and the shop says what
batch a pack comes from and sells a batch's last-day units cheaper.*

## Context

The phone app remembered its own orders and worked out their progress from the hold and the pick job. That was a
bridge, said to be one. It could not survive a second phone, a reinstall or a delivery stage, and nothing on the
server knew who had ordered what.

There was also no design document for the remaining parts (orders, delivery, maps, requests to farms). The owner
asked for one, with the reasoning for every choice. It is `docs/DESIGN.md`; this entry covers how its section 2 was
built and what the build taught.

## What was built

| Piece | What it does |
| --- | --- |
| `orders`, `order_lines`, `order_events` (migration 0007) | Who, which hub, the address, each line at the price paid, the totals, and every status with its time |
| `POST /v1/orders` | Confirms the customer's hold and writes the order, in one transaction |
| `GET /v1/orders`, `GET /v1/orders/{id}` | The customer's own orders; anyone else's does not exist |
| `POST /v1/orders/{id}/cancel` | Until the hub has packed it |
| Event handlers in `app/modules/orders/service.py` | The order follows the hub: packed, cancelled, a line dropped, a substitute taken |
| `GET /v1/stores/{id}/shop` | Availability, plus the batch the next order would be picked from (use-by date; for a farm lot its grade, harvest date and farm) and a rescue offer for units in their last day |
| Pricing by batch | An order's units from a batch in its last day cost 30% less, in whole rupees; the rest cost the full price |

## Decisions, and why

**The order is written inside the hold's confirmation, not before it and not after it.** Confirming a hold commits
by itself. Writing the order first would leave an order behind when the confirmation is refused; writing it after
would leave a paid hold with no order if the process died in between. So `place` notes who is ordering and where
to, then confirms the hold; the confirmation publishes `order.paid`, and the order module's handler for that event
writes the order in the same transaction. The hold's code was not touched.

**The note is passed in a context variable.** The handler needs the customer and the address, and an event's
payload is not the place for a home address: events are logged and relayed to the staff's live feed. A context
variable is set around the one call and cleared after it, and a hold confirmed with nothing set (the hub's demo
desk) makes no order, which is the intended behaviour and not a special case.

**The order's handler runs first.** The hub's own handler for `order.paid` creates the pick job, and may drop a
line at once if the stock has gone. That drop is an event the order must hear, so the order has to exist by then.
Handlers ran in the order modules happened to be imported; `events.subscribe` now takes `first=True` for this one
case, and a test holds it in place.

**A status moves by a guarded update.** `UPDATE orders SET status = 'packed' WHERE order_id = … AND status =
'confirmed'`. An event delivered twice, or after the order has ended, changes nothing and adds nothing to the
timeline.

**The address must be in the zone of the hub that holds the cart.** Without the check a cart held at one hub could
be sent to an address another hub serves. The check is a read of the zone table and never records a miss.

**An order is priced from the pick tasks, not by its own walk through the batches.** The rescue price belongs to
units of one batch, so the bill has to know which batch each unit comes from. The hub decides that when it creates
the pick job, skipping units other orders are waiting for. Repeating that walk in the order module would be a
second copy of a rule that must never disagree with the first. So the order is first written at full prices, the
hub creates its tasks, and on the hub's "job created" event the order's lines are rebuilt from those tasks: one
line per item and price. Eight packs of milk with six in their last day become six at 20 and two at 28.

**A job sent back to the queue is not priced again.** The hub publishes "created" a second time when a stalled
order returns to the queue, by which time some of its lines are in a tote and no longer pending. That event
carries a reason; only the first, without one, prices the order. A test sends the second by hand.

**A dropped unit comes off the dearer line.** When an order holds one item at two prices and the hub cannot find a
unit, the event does not say which unit. Taking it from the dearer line means the customer is never left paying
the full price for a pack that did not come.

**The shop's list is a new endpoint, not a change to availability.** Availability is the most-called read, is
cached, and is what every existing screen and test reads. The shop adds three queries for the batch facts on top
of that cached list, and leaves it as it was.

## One mistake

The migration was changed after it had been applied. `list_price` was added to migration 0007 an hour after the
first version had run on the dev server's test database. That database then said it was up to date and was
missing a column, and thirteen tests failed with an error about SQL, not about the change. Nothing else had the
migration, so it was put right by stepping that one database down and up again with the migration tool. Had the
first version been merged or deployed, the right change would have been a new migration.

## What was checked

- 24 tests for orders and 10 for the shop's list, on PostgreSQL: the order records who, where and at what price; asking twice makes one order
  and one pick job; an address outside the zone is refused and the hold stays held; an expired hold makes no order
  and its items go back on sale; a hold paid at the hub's desk makes none; the order follows the hub to packed;
  cancelling gives the stock back and is safe to repeat; a packed order cannot be cancelled; a line the hub cannot
  find leaves the bill, and an order with nothing left is cancelled; orders are private to their owner; a produce
  line reads "Tomato" and "500 g"; last-day units cost the rescue price and the rest the full price; the shop
  names the batch picked first, skips units another order is waiting for and never describes an expired batch.
- The migration builds exactly the tables in `models.py` (the suite's own check).
- The whole suite, on the dev server and on AWS.

## What it leaves open

- **The app does not use it yet.** The phone was being tested against staging while this was written, and
  changing the app's code would have reloaded it mid-test. The switch follows once this is deployed.
- **The price shown and the price charged can differ.** The shop says how many units are at the rescue price; if
  someone else buys them first, the order is charged the full price and says so in its lines. The hold does not
  yet answer with a quote.
- **A farmer's asking price does not set the shelf price.** The pack's price is still the item's list price.
- **Nothing after packed.** Pooled, out for delivery and delivered are in the table of statuses and nothing sets
  them: that is section 4.
- **No refund.** Dropped lines come off the bill; with payment a stand-in there is no money to return.

## Sources

- `docs/DESIGN.md`, section 2, for the decisions and what was considered and not taken; its own source list covers
  the maps and delivery choices.
- Seen ourselves: every item under "What was checked", from the test runs.
