# Customers buy fixed packs; farmers deliver kilograms

*23 November 2026. A decision that departs from the HLD, made before the supply side is built.*

## Context

The HLD describes stock in kilograms end to end: a listing in kg, hub inventory in kg, an order line in kg, and
"produce sold by weight is weighed at packing, and the bill follows the actual kg" (HLD 6). The code this project
grew from counts whole units everywhere: stock levels, holds, pick tasks, receipts, counts, forecasts, and about six
hundred tests that check those counts stay right under concurrency.

## Decision

- **The customer buys a sellable unit, not a weight.** A catalogue item is a pack ("Tomato 500 g"), a piece with a
  weight range ("Cauliflower, 1 piece, 400 to 600 g") or a bunch ("Coriander, 1 bunch"). The price is per unit.
- **The farmer deals in kilograms.** A listing, a stock request, the weighing at the hub and the quality check are
  all in kg, as the HLD says.
- **The hub turns kilograms into units at putaway.** Accepted kg of a lot become a whole number of units of the
  item's pack size; what does not fill a unit is recorded as trim loss on the goods receipt. From there on, stock is
  whole units, as it is today.
- **Price is still set per batch** (HLD 3: prices move daily), now as a price per unit for that batch.

## Why

**It is how the reference apps sell produce.** Swiggy Instamart's vegetable listings show fixed packs of 250 g and
500 g, loose items such as onions as a 1 kg unit, single pieces with a stated weight range (cauliflower, 400 to
600 g; broccoli, 180 to 300 g) and bunches (curry leaves, 50 to 60 g). None of them bills by the gram.

**Whole units keep the hardest part of the system intact.** The no-overselling guarantee is a conditional update on
an integer count, and the tests around it (twenty buyers racing for the last unit, counts and adjustments taking
turns, the stock audit) are the most valuable thing inherited from the prototype. Moving every quantity to a weight
would rewrite all of it. We estimated two to three of the eleven days left.

**Weighing happens once, where it matters.** The farmer is paid on accepted kg at the hub, which is the HLD's
quality checkpoint. Nothing downstream needs a scale.

## What it costs or leaves open

- The bill no longer follows the actual weight of what was packed. A pack promises its weight; the hub must pack to
  it. Pack weight tolerance is not modelled.
- Trim loss (kg that do not fill a last unit, and what is cut away when packing) becomes a number to watch. It
  belongs beside spoilage in the metrics.
- The forecast and the newsvendor order quantity (HLD 10.6) work in units per item; a stock request to farms turns
  units back into kg with the pack size.
- A piece sold with a weight range is counted as one unit at its typical weight when converting kg to units.

## Sources

- Swiggy Instamart, fresh vegetables listings (packs, pieces with weight ranges, bunches), Hyderabad and Delhi:
  https://www.swiggy.com/instamart/city/hyderabad/sc/fresh-vegetables/fresh-vegetables-6821d56d09ab2e00019aa5db and
  https://swiggy.com/instamart/city/delhi/sc/fresh-vegetables/fresh-vegetables-64a7a842bf4fdc0001f5f54b
- MetricsCart, "Fresh vegetables on Swiggy Instamart" (category report, May 2026):
  https://metricscart.com/quick-commerce-analytics/reports/swiggy-instamart/fresh-vegetables-on-swiggy-instamart/
- Our own estimate, not measured: the two to three days for a move to weights.
- Not found: a source for Blinkit's pack sizes. The search returned none, so Blinkit is not cited here.
