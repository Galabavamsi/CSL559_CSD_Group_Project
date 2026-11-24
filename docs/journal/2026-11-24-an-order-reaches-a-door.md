# An order reaches a door: agents, trips and a four-digit code

*24 November 2026. Until today an order stopped at Packed. The part of the delivery design an order needs to
reach a door is now built: a hub's packed orders are grouped into a trip, an agent on duty takes it, checks the
bags out, and hands each over against a code the customer reads out. One rule of the design did not survive its
first test and was rewritten.*

## Context

The owner will show the app at IIT Bhilai and asked for "a delivery at least". The design for delivery was
written the day before (`docs/DESIGN.md`, section 4) and none of it was built: a packed order was given a
made-up rider and the customer's screen showed four empty boxes where a code should be.

## What was built

| Piece | What it does |
| --- | --- |
| `agent_profiles`, `trips`, `trip_stops` (migration 0009) | An agent's hub and whether they are on duty; a round from a hub; the orders on it, in the order they are dropped |
| `app/modules/delivery/service.py` | Forms trips, gives them to agents, checks bags out, hands orders over or records why not |
| `GET /v1/agent`, `POST /v1/agent/hub`, `/duty` | The agent's own state: hub, duty, and the trip they are on |
| `POST /v1/agent/trip/bags/{order}/load` | The agent confirms a bag at the hub; when all are confirmed the trip is out |
| `POST /v1/agent/trip/stops/{order}/deliver`, `/fail` | The door: the customer's four digits, or the reason it could not be handed over |
| `POST /v1/admin/agents`, `GET /v1/stores/{id}/dispatch` | The platform team makes an agent's account; the hub sees bags waiting, trips and agents |
| The order a customer sees | Moves through pooled, out for delivery and delivered, with the code, the agent's name and how many orders share the trip |
| The agent's screens in the app | Choose a hub, go on duty, collect the bags by crate slot, and hand over at each stop |

## Decisions, and why

All of section 4 of the design applies; 4.10 lists what differs in what was built. The ones that needed thought:

**The code is worked out, never stored.** `HMAC(server secret, order id)`, reduced to four digits. The customer's
app has to show it at any time, so a one-way hash in the database would not do, and the other choice is a readable
code in a table. Worked out on request, a copy of the database holds no codes at all. A test reads the column
names of the four tables involved to keep it that way. The agent's screen is never sent the code.

**Five wrong codes lock the hand-over.** Four digits can be guessed one time in ten thousand; five tries, by an
agent whose name is on the trip, is what makes that acceptable. A wrong code is counted and saved before the
answer is sent, so a retry cannot be used to get a free guess. A malformed code (three digits, a letter) is
refused before it is compared and is not a try.

**A trip is formed inside the packing transaction.** The hub's "packed" event is heard by the orders module,
which marks the order packed, and then by delivery, which looks for packed orders. Both run before the packing
commits, so an order cannot be packed without delivery having looked at it. The order of those two listeners
matters and is pinned by a test, as the same question was for placing an order.

**One trip-forming at a time per hub.** Packing, an agent coming on duty, an agent finishing, and the timer can
all try at once. A database lock per hub makes them take turns, and claiming an agent is a guarded update as
claiming a pick job is, so a trip cannot have two agents or an agent two trips.

**Agents choose their hub and may sign up, on staging only.** The design has the platform team create agents.
One person showing the whole flow needs to be customer and agent with two email addresses and no admin console,
so two settings allow it. They are off unless turned on.

## What went wrong

**The sweep sent an agent out with one bag while two waited.** Section 4.2 cut the circle of waiting orders into
fixed wedges and sent the wedge with the oldest order. With three orders for one building and room for two, the
cut fell so that the oldest order was alone in the last wedge. The test that found it was the plainest one: "a
trip takes no more than its most". The rule is now the longest-waiting order and its nearest neighbours by
direction, which always fills the trip. The sweep divides everything at once; here trips are formed one at a
time, as agents come free, and that difference was missed when the section was written.

## What was checked

- 25 new tests of delivery; the whole suite, 793, passes on the dev server and on AWS, where the migration is
  also compared with the models.
- The end-to-end run and what it showed are in the pull request.

## What it leaves open

- **Road distances.** Legs are straight lines times 1.7. The order of stops is right for a few addresses in one
  direction; the kilometres are an estimate.
- **The bag that comes back.** A failed hand-over ends as `delivery_failed`. The hub's part, shelf or write-off,
  is not built.
- **Where the agent is.** No positions, no map, no time of arrival.
- **Releasing a locked code**, and the dispatch panel as a page.
- **Someone still has to pick and pack.** A demo by one person needs the hub's picker page between the customer's
  order and the agent's trip.

## Sources

- B. E. Gillett and L. R. Miller, "A Heuristic Algorithm for the Vehicle-Dispatch Problem", *Operations Research*
  22(2), 1974 (the sweep method, which section 4.2 started from and moved away from):
  https://pubsonline.informs.org/doi/10.1287/opre.22.2.340
- IETF, RFC 2104, "HMAC: Keyed-Hashing for Message Authentication": https://www.rfc-editor.org/rfc/rfc2104
