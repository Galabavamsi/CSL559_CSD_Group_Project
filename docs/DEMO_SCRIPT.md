# Demo script

A ten-minute walk through the prototype for a presentation. Each step says what to click and what
to say. Rehearse it twice; press **Reset demo data** on the ops desk before every run.

## Before you start

```bash
python -m uvicorn app.main:app
python scripts/generate_sales.py     # in a second terminal, after every reset
```

The generator gives the forecast in section 7 two months of sales; the demo data alone has one week, too
little to forecast from the same weekday or to measure forecast error.

Open http://localhost:8000 in **two browser windows** side by side (you need the second one for
step 3). Keep the store selector on *DS-01 Central*.

## 1. The three stations (30 seconds)

> "This screen shows three people in one dark store. On the left, a customer's phone. In the
> middle, a picker's handheld. On the right, the store manager's desk. Everything they do goes
> through the same API a real app would use."

## 2. Only sellable items are shown (1 minute)

1. Customer station: choose *Home near DS-02 North* and press **Check delivery**.
2. Point at the note under the list: one item is hidden. Bananas are out of stock in that store.
3. Choose *Home far outside the city*: "No store delivers here yet."
4. Go back to *Home near DS-01 Central*.

> "The app first asks which store serves this address. Then it only lists what that one store can
> actually deliver. That is FR-1 and FR-2."

## 3. The last ice cream (2 minutes)

This is the centrepiece. The demo data has exactly **one** vanilla ice cream in store 1.

1. In **both** windows, add 1 *Vanilla ice cream* to the cart.
2. In window A press **Hold my items**. A blue panel appears with a 10-minute countdown.
3. On the ops desk, find ice cream in the stock table: *On hand 1, Held 1, Available 0*.
4. In window B press **Hold my items**. It is refused straight away: "Not enough stock... Nothing
   was held."

> "Two customers wanted the last unit. The database decided in a single statement who got it, and
> the other was told before paying, not after. On hand is still 1: the item has not left the shelf,
> it is only promised. Our tests run this race with twenty buyers at once and exactly one wins."

5. In window A press **Cancel order**. Held goes back to 0. In window B the ice cream can now be held.

## 4. A paid order, picked oldest-first (2 minutes)

1. Customer: add 8 *Toned milk* and 2 *Basmati rice*. **Hold my items**, then **Pay now**.
2. Ops desk: "Waiting for a picker" is 1, and the event feed shows `order.paid`.
3. Picker: press **Get next order**.

> "The milk line is split across two bins. Six come from batch M-OLD, which expires tomorrow, and
> only two from the newer batch. That is first-expiry-first-out. The lines are also sorted in
> walking order, nearest bin first."

4. On the rice line (the first one) press **Scan a wrong item**: rejected, nothing changes.
5. Press **Scan item** on the rice line.

## 5. An empty shelf (1 minute)

1. On the first milk line (bin C-01-01, batch M-OLD) press **Not on shelf**. The line moves to
   bin C-01-04.

> "The picker says the bin is empty. The system corrects the count, writes a ledger entry so we
> know who found the gap, and looks for the same item elsewhere. Had there been none, it would have
> dropped the line and released the hold so the customer is not charged."

2. Press **Scan item** on each line that is left.

## 6. Packing commits the sale (1 minute)

1. Before packing, point at the milk row on the ops desk: *Held* still shows the order's units.
2. Press **Mark packed**.

> "Only now does On hand go down. Until this moment a cancellation only had to release a hold.
> That is why a failed payment can never leave the stock count wrong."

3. Press **Rider collected the bag**. "Handed to rider" becomes 1; the average pack time appears.

## 7. Restocking (2 minutes)

1. Ops desk: the bread row is highlighted; it is below its reorder point.
2. Press **Check what needs reordering**. A transfer order appears.
3. Press it again: "Nothing to reorder".

> "Stock that is already on its way counts, so the system never orders the same thing twice."

4. Press **Hub dispatches truck**, then **Receive truck**.

> "Each item is put in a bin in the right temperature zone and is on sale the moment it is put away."

5. Customer station: bread now shows the new quantity.
6. Press **Recalculate forecasts**. Reorder points for the items with sales history change.

> "Each item's demand is forecast from the same weekday over the last four weeks, the model that won our
> backtest. Reorder points follow the formula in section 6.2 of the HLD, and the safety stock covers how wrong
> the forecast was over the last two weeks."

## 8. A busy store (30 seconds, optional)

Place and pay for six small orders without picking them. The store tile turns to *Busy*, and
**Check delivery** now quotes an ETA five minutes longer.

> "When a store's backlog passes a threshold it protects itself by quoting a longer delivery time."

## 9. Close (30 seconds)

Open http://localhost:8000/docs.

> "Every action you saw is one of these API calls. The code has one module per service in our HLD,
> and 25 automated tests. What you saw is a prototype: SQLite instead of PostgreSQL, an event table
> instead of Kafka, and no logins yet. Each of those gaps is a planned task for one of us."

## If something goes wrong

| Problem | Fix |
| --- | --- |
| Odd numbers from an earlier run | **Reset demo data** |
| "The hold ran out" | **Release expired holds**, then order again |
| Picker says no orders are waiting | The order was not paid, or the store selector is on the other store |
| Page will not load | Check the terminal running `uvicorn`; restart it |
