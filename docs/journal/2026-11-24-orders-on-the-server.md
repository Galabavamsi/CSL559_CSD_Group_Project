# Orders on the server, and a design written down

*24 November 2026. With no earlier design to follow for what is left, one was written with a reason for each
decision. Its first piece is built: a customer's order is now a record on the server.*

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

## What was checked

- 21 tests for orders, on PostgreSQL: the order records who, where and at what price; asking twice makes one order
  and one pick job; an address outside the zone is refused and the hold stays held; an expired hold makes no order
  and its items go back on sale; a hold paid at the hub's desk makes none; the order follows the hub to packed;
  cancelling gives the stock back and is safe to repeat; a packed order cannot be cancelled; a line the hub cannot
  find leaves the bill, and an order with nothing left is cancelled; orders are private to their owner; a produce
  line reads "Tomato" and "500 g".
- The migration builds exactly the tables in `models.py` (the suite's own check).
- The whole suite, on the dev server and on AWS.

## What it leaves open

- **The app does not use it yet.** The phone was being tested against staging while this was written, and
  changing the app's code would have reloaded it mid-test. The switch follows once this is deployed.
- **Prices are the list price.** The price per batch and the rescue price are section 3 of the design.
- **Nothing after packed.** Pooled, out for delivery and delivered are in the table of statuses and nothing sets
  them: that is section 4.
- **No refund.** Dropped lines come off the bill; with payment a stand-in there is no money to return.

## Sources

- `docs/DESIGN.md`, section 2, for the decisions and what was considered and not taken; its own source list covers
  the maps and delivery choices.
- Seen ourselves: every item under "What was checked", from the test runs.
