# The app moves onto the server's orders, a price that could rise unseen, and a key for map tiles

*24 November 2026. Orders and the shop's list were deployed to staging, and the phone app was switched from its
own bridge to them. Reading the app's checkout for that switch found a customer could be charged more than the
screen said. Separately, the owner asked for the map tiles key; it exists and a map of Bhilai has been drawn
with it.*

## Context

The server gained orders and the shop's list the day before (see
[the previous entry](2026-11-24-orders-on-the-server.md)). The app still kept its orders on the phone and read
plain availability. Three things were asked for or due: deploy what was merged, create the key for map tiles, and
move the app over.

## What was built

| Piece | What it does |
| --- | --- |
| Staging on `main` at 95644a5 | Migration 0007, the four order endpoints and `GET /v1/stores/{id}/shop` are live |
| API key `farm2home-map-tiles` | Reads Amazon Location map tiles in Mumbai, and nothing else; ends 31 March 2027 |
| `GET /v1/reservations/{id}/bill` | What a held cart costs if paid this moment, from the hub's own allocation |
| `expected_total` on `POST /v1/orders` | An order that would cost more than the customer saw is not placed: `409 price_changed`, hold kept |
| The app's server client | Products from the shop's list; orders placed, listed, read and cancelled on the server; the on-phone order store is deleted |
| The app's cart and checkout | The cart charges the last-day units first and the rest at the usual price; the checkout shows the hub's bill |

## Decisions, and why

The reasoning is in `docs/DESIGN.md`: section 1.2 for the key and section 3.3 for the bill. In short:

**The key reads tiles and nothing else.** It is handed to every phone and browser that draws the map, so it can
be copied. AWS's own advice is to allow a key only the actions the application needs, and to give it an end date.
Place search was planned on the same key and was taken off it: search goes through our server, where it can be
limited to the city and capped.

**The key is not limited to a web address.** AWS recommends that for web pages. The same map will run inside the
app's web view, which has no fixed address. AWS can also limit a key to one Android or iOS app; that is for the
installable build.

**The bill comes from the function that picks.** The checkout's total was the phone's own sum. A hold sets units
aside, not batches, so two customers holding the same six last-day packs were both shown the lower price, and
the one who paid second was charged the full price without being told. Now the checkout shows what the hub's
allocation would charge, the app sends back the total it showed, and a higher price is refused with nothing
paid. A lower price is simply charged.

**Refused inside the payment, then undone.** The order is priced from its pick tasks, which exist only once the
payment is under way. So the check runs there and raises; the confirmation, the order and the pick job are all
in one transaction and are rolled back together. The test checks that the hold is still held, that stock adds
up, and that the second attempt at the new total goes through.

## One thing the deploy check showed

The Bhilai hubs on staging have nothing on their shelves: their shop lists are empty until a farmer's lot is
taken in there. Bangalore's first hub has its seeded stock. A test order in Bhilai needs a lot listed and
received first, which is the flow the demo shows anyway.

The same check showed a batch dated 23 November still on sale at one in the morning on the 24th, India time. The
server takes "today" from its own clock, which is UTC, so a use-by date ends at 05:30 in India instead of at
midnight. Not fixed in this change; it is the next thing to fix, because delivery windows will need India's clock
too.

## What was checked

- **Deploy.** 736 tests passed on AWS before the build. From the dev server afterwards: the shop's list answers
  for a hub with stock (16 items, one at a rescue price) and for an empty one; the order endpoints refuse a call
  with no login (401) and are in the API description; the 12-step smoke test passes.
- **The key.** With it: the Standard style with India's view of its borders, its drawings and letters, and tiles
  over Bhilai at two zoom levels, all answered 200. Without it or with a wrong one: 403. A place search and a
  static picture with it: 403. Then MapLibre GL JS 4.7.1 drew Bhilai in a browser with the three hubs as pins, no
  errors; at street level around the Civic Centre hub it names streets, the canal, the park and the market.
- **The bill and the refusal.** Eight new tests: the bill equals what the order then costs; two customers and
  six rescue packs; a price that fell; a total within half a paisa; who may read a bill; malformed totals.
- **The app.** Type-checks. Tried on the phone against staging as far as staging's version allows (see below).

## What it leaves open

- Staging does not have the bill or the refusal until this change is merged and deployed. Against the current
  staging the app's checkout falls back to its own sum and the server ignores `expected_total`.
- The handbook PDF and the video still describe orders as kept on the phone. They are not being rebuilt.
- The key's value is not stored anywhere but AWS. When the map is built, the server will hand out the style
  address from its settings.
- India's clock for "today" (above).

## Sources

- AWS, "Best practices" for Amazon Location, API key optimization:
  https://docs.aws.amazon.com/location/latest/developerguide/auth-best-practices.html
- AWS CLI reference, `location create-key` (the actions a key may allow):
  https://docs.aws.amazon.com/cli/latest/reference/location/create-key.html
- AWS, "How to set the political view of a map":
  https://docs.aws.amazon.com/location/latest/developerguide/how-to-set-political-view-map.html
- AWS, "How to display a map" (MapLibre GL JS with an API key in the style address):
  https://docs.aws.amazon.com/location/latest/developerguide/how-to-display-a-map.html
