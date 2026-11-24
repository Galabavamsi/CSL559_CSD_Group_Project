# Hub desk script

A walk through the hub desk page (`web/index.html`) on a laptop: one order at three stations side by side, to show
the stock rules (a hold, the oldest batch first, the sale committed at packing, restocking), then the API, the
network map and the ops dashboard. About fifteen minutes; sections 8 and 10 are optional. Each step says what to
press and what to say. Rehearse it twice.

To show the whole flow from a farmer's lot to a customer's door, from phones, use
[`DEMO_ON_A_PHONE.md`](DEMO_ON_A_PHONE.md) instead.

The hub desk is the dark-store prototype's page, kept. Its customer station shops at Bangalore's two hubs, DS-01
Central (hub 1) and DS-02 North (hub 2), which sell the dark store's groceries, and the steps below rely on what the
demo data plants there: one vanilla ice cream left at hub 1, its milk in two batches, its bread below the reorder
point, and no bananas at hub 2. Orders paid at the desk have no customer account, so they make a pick job but no
order record, and their bags go to made-up riders, not to delivery agents.

## Where to run it

**Your own copy (best).** The planted situations exist only on fresh demo data, so run the app yourself and reset
it before every run. It needs PostgreSQL with PostGIS (Docker gives you one). On the owner's Windows laptop
Application Control can block the compiled `h3` library, and the app then does not start: use another machine.

**Staging** (https://staging.farm2home.galabavamsi.com/) works too, with these differences:

- The page asks for the staff password in a sign-in box of its own the first time it logs in, and the browser
  remembers it. The password is in AWS Secrets Manager, `farm2home/staging/staff-password`
  ([`infra/README.md`](../infra/README.md) says how to read it). In `/docs`, use it in place of `demo`.
- The stores menu lists six hubs: DS-01 Central and DS-02 North in Bangalore (1 and 2), and BH-01 Civic Centre,
  BH-02 Nehru Nagar, BH-03 Durg and BH-04 IIT Bhilai in Bhilai (3 to 6). Keep it on hub 1 or 2: the customer
  station only knows addresses in Bangalore.
- The numbers are whatever earlier use left. The planted situations are probably gone, and packaged goods are
  reordered by a timer every 15 minutes.
- **Never press Reset demo data on staging.** It empties every table for everyone, the phone app's accounts,
  farms, orders and trips included. Leave sections 9 (step 5), 10 and the "Open a hub here" button alone there too:
  they change shared data.
- An order no picker starts within 45 seconds is picked and packed by the app (`DEMO_AUTOPACK`). Press
  **Get next order** soon after **Pay now**.
- Press **Rider collected the bag** only for an order you paid for at the desk. A phone customer's order at the
  same hub is collected by its delivery agent in the app, and once handed to a made-up rider the agent cannot check
  it out.
- Some networks block the staging address; mobile data works.

## Before you start (your own copy)

Start the database and the app without the demo settings (`DEMO_PRODUCE`, `DEMO_HUBS`, `DEMO_SUPPLY`): the script
expects Bangalore's two hubs with groceries only.

```bash
docker compose up -d postgres
RATE_LIMIT_PER_SECOND=0 REPLENISHMENT_INTERVAL_MINUTES=0 python -m uvicorn app.main:app
```

```powershell
docker compose up -d postgres
$env:RATE_LIMIT_PER_SECOND = "0"; $env:REPLENISHMENT_INTERVAL_MINUTES = "0"; python -m uvicorn app.main:app
```

The rate limit is off so the load test below is not refused. Automatic replenishment is off so the transfer order in
section 7 comes from the button, not from the timer half-way through the demo.

Then, in a second terminal, from the repository's folder:

```bash
python scripts/load_test.py --seconds 30 --reset   # once, before the audience arrives; keep its table for section 12
```

The load test places real orders. Afterwards, open http://localhost:8000, press **Reset demo data** on the ops desk
and confirm, then run:

```bash
python scripts/generate_sales.py                   # after every reset
python scripts/generate_demand.py                  # after every reset
```

The sales generator gives the forecast in section 7 two months of sales; the demo data alone has one week, too
little to forecast from the same weekday. The demand generator adds the delivery lookups the map in section 11 needs,
including ones no hub could serve.

Open http://localhost:8000 in **two browser windows** side by side (window A and window B; section 3 needs both).
Keep the stores menu on *DS-01 Central*.

## 1. The three stations (30 seconds)

> "This page shows three people at one hub. On the left, a customer's phone. In the middle, a picker's handheld. On
> the right, the hub's desk. Everything they do goes through the same API the phone app uses."

## 2. Only sellable items are shown (1 minute)

1. Customer station: choose *Home near DS-02 North* and press **Check delivery**: "DS-02 North delivers here in
   about ... minutes."
2. Point at the note under the list: "1 item is hidden because the store has none to sell." Bananas are out of
   stock at that hub.
3. Choose *Home far outside the city* and press **Check delivery**: "No store delivers here yet", with the nearest
   hub and its distance.
4. Choose *Home near DS-01 Central* and press **Check delivery** again.

> "The page first asks which hub serves this address. Then it lists only what that hub can deliver now."

## 3. The last ice cream (2 minutes)

This is the centrepiece. The demo data has exactly **one** vanilla ice cream at hub 1.

1. In **both** windows, add 1 *Vanilla ice cream 500 ml* with its **+** button.
2. In window A press **Hold my items**. A blue panel appears: "Items held for you", with ten minutes to pay.
3. On the ops desk, find the ice cream in the stock table: *On hand 1, Held 1, Available 0*.
4. Look at window B. Within five seconds its list drops the ice cream, since none is left to sell, but its cart
   still holds one. Press **Hold my items** there. It is refused at once: "Not enough stock for Vanilla ice cream
   500 ml (0 left). Nothing was held; change your cart and try again."

> "Two customers wanted the last unit. The database decided in a single statement who got it, and the other was told
> before paying, not after. On hand is still 1: the item has not left the shelf, it is only promised. Our tests run
> this race with twenty buyers at once, and exactly one wins."

5. In window A press **Cancel order**. *Held* goes back to 0. Within five seconds window B lists the ice cream again,
   and **Hold my items** there now works. Press **Cancel order** in window B too.

## 4. A paid order, picked oldest batch first (2 minutes)

1. Window A, customer station: add 8 *Toned milk 500 ml* and 2 *Basmati rice 1 kg*. Press **Hold my items**, then
   **Pay now**. The order appears with "Paid. Waiting for a picker."
2. Ops desk: *Waiting for a picker* is 1, and *Latest events* shows `order.paid`. Point at window B: its ops desk
   shows the same within a second, without a reload.

> "Every change is written as an event, and each hub's screens are told over a live connection. If that connection
> drops, the page checks every three seconds and reconnects on its own."

3. Picker station: press **Get next order**.

> "The milk is split across two bins. Six come from batch M-OLD, which expires tomorrow, in bin C-01-01, and only
> two from the newer batch in C-01-04. The batch that expires first is picked first. The lines are in walking order,
> nearest bin first, so the rice on shelf A-01-04 comes before the fridges."

4. On the rice line press **Scan a wrong item**: refused, and nothing is counted.
5. Press **Scan item** on the rice line.

## 5. An empty shelf (1 minute)

1. On the M-OLD milk line (bin C-01-01) leave *Found only...* empty and press **Not on shelf**. The line reads "Not
   here: moved to another bin", and a new line for the same six units appears at C-01-04.

> "The picker says the bin is empty. The system corrects the count, writes ledger rows so we know who found the gap,
> opens a count of that bin, and looks for the same item elsewhere. Had there been none, it would have dropped the
> line, released the hold so the customer is not charged, and offered something similar instead."

2. Press **Scan item** on each line that is left.

## 6. Packing commits the sale (1 minute)

1. Before packing, point at the milk row on the ops desk: *Held* still shows the order's 8 units.
2. Press **Mark packed** (crate slot S-01): "Packed into S-01. The stock has now left the books."

> "Only now does On hand go down. Until this moment a cancellation only had to release a hold. That is why a failed
> payment can never leave the stock count wrong."

3. Press **Rider collected the bag**. The order's rider checks in and the desk scans the bag: "Rider R-12 collected
   order ... from S-01" (the rider's number varies). *Handed to rider* becomes 1.

> "A rider gets only the bag of the order they were assigned. Another rider, or another order's bag, is refused. In
> the phone app this hand-over is a delivery agent checking the bag out for a trip."

## 7. Restocking (2 minutes)

1. Ops desk: the bread and ice cream rows are highlighted; both are below their reorder point.
2. Press **Check what needs reordering**. A transfer order appears, for the items below their reorder point.
3. Press it again: "Nothing to reorder: every item is above its reorder point or already on its way."

> "Stock that is already on its way counts, so the system never orders the same thing twice. It orders in whole
> cases, and only as much as the shelves have room for."

4. Press **Hub dispatches truck**, then **Receive truck**: "Truck received and put away", with each item and the bin
   it went to.

> "Each item is put in a bin of the right temperature zone, and is on sale the moment it is put away."

5. Customer station: the bread now shows the new quantity.
6. Press **Recalculate forecasts**: "Forecasts recalculated with the weekday average model. Reorder points updated
   for ... items."

> "Each item's demand is forecast from the same weekday over the last four weeks, the model that won our backtest.
> The reorder point covers the demand until a delivery arrives, plus a safety stock sized by how wrong the forecast
> was over the last two weeks."

## 8. A busy hub (2 minutes, optional)

1. Place and pay for six small orders without picking them. The *Store* tile turns to *Busy*, and **Check
   delivery** now quotes five minutes more.

> "When a hub's backlog passes a threshold it protects itself by quoting a longer delivery time."

2. On the picker station press **Get next order**: "Busy store: 3 orders in one walk." Each line shows its tote (A,
   B or C), and the lines of all three orders are in one walking order.
3. Press **Scan item** on every line, then **Mark tote A packed**, then B and C. The crate slot moves on by itself.

> "At peak one walk serves three customers instead of one. Our comparison script, scripts/compare_picking.py,
> measured 48% less walking over 30 orders."

## 9. Logins: roles, hubs and a safety buffer (2 minutes)

Open http://localhost:8000/docs.

1. **POST /v1/auth/login**, *Try it out*, body `{"username": "picker1", "password": "demo"}`, *Execute*. Copy the
   `access_token`.
2. **Authorize** (top right): paste the token, *Authorize*, *Close*.
3. **GET /v1/pickers/{picker_id}/next-task**, *Try it out*, `picker_id` *picker1*, `store_id` *2*, *Execute*.
   Refused with 403: "You can only act on your own store".

> "The picker works at hub 1. The token says so, and every staff call checks the role and the hub before it does
> anything."

4. Log in again as `manager1`. In **Authorize**, press *Logout*, paste the new token, *Authorize*.
5. **PUT /v1/stores/{store_id}/stock-settings/{sku_id}**, `store_id` *1*, `sku_id` *7* (rice), body
   `{"safety_buffer": 5}`, *Execute*. The answer shows `atp` 5 lower than `on_hand`.
6. Back on the hub desk: within five seconds the customer station shows 5 fewer rice. The ops desk table catches up
   at its next event; reload the page to show it at once.

> "A manager can hide a few units of an item whose count is often a little off, so customers are never sold the last
> unit that may not be on the shelf."

## 10. Fast movers near the packing desk (1 minute, optional, your own copy only)

Still logged in as `manager1` in `/docs`. Do this after the picking steps: it can move milk's second batch.

1. **GET /v1/slotting/plan**, `store_id` *1*, *Execute*. `homes` ranks each zone's items by how fast they sold over
   the last 14 days, fastest in the bin nearest the packing desk; `moves` lists the batches to move there.
2. **POST /v1/slotting/apply**, `store_id` *1*, *Execute*. `moved` says what went where. A batch a picker is on the
   way to would be under `skipped`, and no bin is ever filled past its capacity.

> "Fast movers live nearest the packing desk. Stock is moved, never gained or lost: two ledger rows per batch. New
> deliveries go straight to an item's planned bin, so the shelves re-sort themselves as stock arrives."

3. In the terminal: `python scripts/compare_slotting.py` (a few seconds, on a throwaway copy of the data).

> "Orders of shelf items walk less. Most orders also hold a chilled item, and the fridges are at the far end of the
> walk, so the overall saving is small: moving the fridges nearer the desk would help more, and that is a layout
> change, not slotting."

## 11. Where to open the next hub (1 minute)

Open http://localhost:8000/network.html (it signs in as `ops`).

1. The blue circles are the hubs' delivery zones; the cells each hub serves are worked out from H3 hexagons. Green
   cells are paid orders.
2. The red cells are addresses customers asked about that no hub could serve.
3. The dashed yellow circles are the suggested new sites. The list on the right says how many of those turned-away
   customers each would reach. Its **Open a hub here** button really opens one: do not press it unless you mean to.

> "Every lookup we could not serve is recorded by hexagon, never by address. The suggestions pick, one at a time,
> the site that reaches the most of them, outside our current zones. A customer who asks for delivery in the app
> counts five times."

On staging, `network.html?city=bhilai` shows Bhilai's four hubs.

## 12. The ops dashboard and the load test (1 minute)

Open http://localhost:8000/ops.html (it signs in as `ops`).

1. *Needs action now* comes first: stalled orders, bags waiting too long for a rider (the totes from section 8, if
   you left them), items out of stock. Then each measure beside its target, and whether it is met. A measure with
   no data yet (for example inventory accuracy before the first cycle count) says so instead of showing a made-up
   number.
2. Switch to the terminal with the load-test table from *Before you start*.

> "Thirty seconds of mostly reads with some holds. The read p99 is what the 100 ms target is about. This is one
> laptop with a database in Docker, so it shows where the time goes. Our recorded run, on a four-CPU server with the
> app, the database and the load all on one machine, answered availability in 130 ms at the 99th percentile: that
> target is missed, and the report says so."

## 13. Close (30 seconds)

Back on http://localhost:8000/docs.

> "Every action you saw is one of these API calls, and every staff call carries a login with a role and a hub. Each
> service is its own module, and one automated test walks this script through the API, from the order to a final
> stock audit. This page pays without a customer and hands bags to made-up riders; the phone app does both for real,
> with sign-in, an order record, trips and a code at the door."

## If something goes wrong

| Problem | Fix |
| --- | --- |
| Odd numbers from an earlier run | **Reset demo data** (your own copy only), then run the two generators again |
| "The hold ran out" | **Release expired holds**, then order again |
| The picker says no orders are waiting | The order was not paid, the stores menu is on another hub, or (on staging) the app packed it after 45 seconds |
| The page will not load | Check the terminal running `uvicorn`, and that the database is up (`docker compose up -d postgres`) |
| A screen looks or behaves as before a `git pull` | The browser kept the old script: reload each page with Ctrl+Shift+R |
| The map has no red cells or suggestions | Run `python scripts/generate_demand.py` (needed after every reset), then **Refresh** |
| The first **Check what needs reordering** says "Nothing to reorder" | The timer already ordered: the app was started without `REPLENISHMENT_INTERVAL_MINUTES=0`, or this is staging. Show the transfer order it raised |
| The staff sign-in box comes back | The password was not accepted: capitals count. On your own copy it is `demo` |
| "Staff sign-in was cancelled" | Reload the page to see the box again |
| A *Try it out* call in `/docs` says 401 | The token was not pasted into **Authorize**, or its 30 minutes are up; log in again |
| "No connection", or the staging page will not open | The network blocks the staging address; use mobile data |
