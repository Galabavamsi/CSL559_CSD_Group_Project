# Farm supply: from a farmer's listing to units on a shelf

*23 November 2026. HLD flow A, the first half of what makes this a farm-to-home system and not a dark store.*

## Context

In the prototype, stock came from a "mother hub" by truck, in whole cases. In the HLD it comes from farms: a
farmer lists produce, the system picks a hub and a drop slot, and the hub weighs, grades and stores it (HLD 5,
flow A, and HLD 6, intake and putaway). The day's earlier decision applies: farmers deal in kilograms, customers buy
fixed units.

## What was built

| HLD step | In the code (`app/modules/farms/`) |
| --- | --- |
| Farmer lists produce: item, kg, price per kg, harvest date | `POST /v1/listings`, for a farm the farmer registered with `POST /v1/farms` |
| Nearest hub with free capacity (PostGIS, filtered by capacity) | `choose_hub`: the nearest open hubs within 60 km, tried nearest first on the GiST index; a hub is passed over if it has no shelves of the item's temperature zone or no room for the weight |
| Farmer gets a drop slot | The next morning intake window (06:00 to 09:00 in the cities' time) that has not started, and never before the harvest date |
| Hub weighs it and grades it A / B / C / Reject | `POST /v1/listings/{id}/intake`: weight received, weight rejected, grade, remarks |
| Accepted kg enter inventory with expiry = harvest date + shelf life | Accepted kg are packed into whole units on a goods receipt, as batch `L<listing id>` with that expiry; the hub's existing putaway steps move them to bins |
| Farmer sees accepted and rejected kg | `GET /v1/listings` shows each listing's quality check |
| Stock is sellable at its bin scan, not when the drop is finished | Unchanged from the prototype's receiving: each line is sellable the moment it is put away |
| Farmer ranking by rejection rate (HLD 10.9) | `rejection_rate`: rejected kg / delivered kg over 30 days, shown on the farm and beside each expected drop |

## Decisions, and why

**Intake reuses receiving; it does not copy it.** The prototype's receiving has rules that took many fixes to get
right: a batch number means one expiry date, units wait "on the dock" until a bin scan, a batch with too little
shelf life left is recorded but never stocked, and nothing overfills a bin. Farm intake opens an ordinary goods
receipt and "scans" the packed units onto it. Every one of those rules then applies to farm produce without being
written again. One test shows it: a lot dropped days late is packed, and the dock refuses it for its shelf life.

**A hub's room counts what is coming, not only what is there.** Free capacity is the hub's capacity minus the
produce on its shelves minus the lots already on their way to it. Without the last term, ten farmers listing in the
same hour would all be sent to the same nearly full hub.

**Too-old produce is refused at listing, not at the dock.** A hub turns away produce with less than half its shelf
life left. If the harvest date and the drop slot already make that certain, the farmer is told when listing, before
making the trip.

**Weights are stored in whole grams.** Accepted kg become units, and what is left is trim. With grams as integers
that sum is exact; with floating-point kilograms it would not be.

**A lot is taken in once.** Intake starts with one conditional update of the listing from "listed" to "received".
Two receivers scanning the same lot at the same moment take turns, and the second is told it is done. A test runs
exactly that race.

**A GPS fix rougher than 50 m is not kept** (HLD 16). A farm's location decides its hub, so a location the phone is
unsure of is refused; a pin placed by hand sends no accuracy and is accepted.

## What was checked

- 30 tests on PostgreSQL with PostGIS, among them: the nearest hub is chosen and a full one passed over; lots on
  their way count against room; a refused intake changes nothing; packs cannot weigh more than was accepted; the
  farmer's rejection rate; who may do what.
- The tests found a real fault before it shipped: a helper renamed for sharing took the same name as a local
  variable and broke the nearest-hub query everywhere it was used.

## What it leaves open

- **Photos.** The HLD wants real photographs of the farm, the lot and the quality check. Not built yet.
- **Grade and price per batch in the catalogue.** The grade is stored and can be traced from a pack on a shelf to
  its lot, but the customer does not see it yet, and the price is still the unit's list price.
- **Slot capacity.** Every lot gets the next morning window; the number of lots a hub can check in one window is
  not limited.
- **Stock requests** (HLD flow D). Here the farmer offers; the hub does not yet ask farms for what it expects to
  sell.
- **Temperature zones.** The HLD has three (ambient, cool, cold). The bins know ambient, chilled and frozen, so
  tomatoes and leafy greens share "chilled" for now.
- **Paying the farmer.** The accepted weight and the asking price are recorded; no payment is.

## Sources

- The project's HLD, sections 5, 6, 10.9 and 16 (flow A, intake and putaway, farmer ranking, GPS rules).
- [Customers buy fixed packs; farmers deliver kilograms](2026-11-23-fixed-packs.md), for why kilograms become units.
- The shelf lives and prices of the demo produce are assumptions for the demo, as HLD 15 says of its own.
