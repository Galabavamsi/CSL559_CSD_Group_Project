# Shops that are never empty, a hub at IIT Bhilai, asking for delivery, and India's calendar

*24 November 2026. The owner signed in on a phone against staging, chose Bhilai, and found a shop with nothing in
it. The same hour: IIT Bhilai, where the demo will be given, was outside every hub's zone; a customer outside a
zone had no way to say so; and some items showed an icon where a photograph should be. This entry covers what was
built for each, and a fault in what the server takes "today" to be.*

## Context

Staging had Bhilai's three hubs since the day before, opened by the demo setting, and nothing on their shelves. A
hub sells only what a farm has brought it, and no farm had. That is correct and useless: the first thing anyone
does with the app is open the shop.

## What was built

| Piece | What it does |
| --- | --- |
| `app/demo_supply.py` | For each produce item a hub is nearly out of, one lot from a demo farm, through the hub's ordinary intake |
| `DEMO_SUPPLY`, a timed job, `POST /v1/admin/demo-supply` | Every half hour when the setting is on (staging), and on request |
| BH-04 IIT Bhilai | A fourth demo hub, half a kilometre from the campus; each demo hub is now opened if it is missing |
| `POST /v1/service-requests`, migration 0008 | A customer asks for delivery where nobody serves; kept as the H3 cell |
| Planning | A request counts as five turned-away lookups; the map and its totals show requests |
| The app's location screen | "Request delivery here" where nobody serves, then how many neighbours asked; IIT Bhilai is the first area |
| `app/clock.py` | The one place that answers "what is the date": India's date, not the server's |
| Photographs and aisles | One photograph for each of the 15 packaged items; those items sit under six shop aisles instead of fifteen one-item groups |

## Decisions, and why

Each is argued in `docs/DESIGN.md`: 1.5 (asking for delivery), 3.4 (the calendar), 8.1 (demo farms), 8.2 (the hub
at IIT Bhilai). The short versions:

**Demo stock goes through the intake.** Writing stock straight onto a shelf would have been ten lines. It would
also have had no listing, no quality check and no farm, and "which farm, what grade, picked when" is what the shop
exists to say. The demo farms call the same functions a receiver's phone does, so their lots have all of it and
the stock audit cannot tell them from a farmer's.

**A new hub for IIT Bhilai, not a wider radius.** The campus is 4 km from the Nehru Nagar hub and a hub serves
3 km. Widening one hub's radius to catch one address breaks the promise of a short ride for everyone else at its
edge. Amazon Location found the permanent campus at Kutelabhata; it also still lists the old transit campus near
Raipur under the same name, which is the kind of answer section 1.2 warned about.

**A request is kept as a cell.** Planning needs the neighbourhood and nothing needs the door, the same rule as
for a lookup that is turned away.

**India's date by an offset, not a time zone in the container.** One time zone, no daylight saving, and the
setting already existed for drop slots. Changing the container's zone would have moved every log line and left
the tests, which run in UTC, testing something else.

## What went wrong

- **The calendar fault was visible on staging and nobody had looked at one in the morning.** A batch dated the
  23rd was on sale, at the rescue price, at 01:00 on the 24th India time. The tests could not catch it: they took
  "today" from the same wrong clock as the code. They now take it from `app/clock.py` too, and the run that
  checked the change happened to fall at 01:43 India time, the very hours where the two dates differ.
- **One new test was wrong, not the code.** It expected no rescue price the day after a batch expired, forgetting
  that the next batch was by then in its own last day.
- **The laptop's AWS sign-in expired in the middle of a deploy.** Nothing had started; the owner signed in again.

## What was checked

- The new and changed tests on the dev server: 77 passed (demo farms, the fourth hub, requests, the calendar,
  accounts).
- The whole suite and an end-to-end run of the app's real web build: see the pull request.
- The app type-checks.

## What it leaves open

- **Delivery itself.** An order still stops at Packed. Agents, trips and the door-step code (design section 4)
  are the next thing to build.
- The photograph for sunflower oil is of olive oil in a plain bottle: no unbranded sunflower oil picture under
  an open licence was good enough. Eight of the new photographs are CC BY, so the credits in `mobile/ASSETS.md`
  have to be shown in the app before any public release, as that file already says.
- Staging's shops show demo farms' lots, so the story "empty until the farmer lists" is now only in the recorded
  demo.
- The weight of five for a request is a guess.
- Sales statistics still count a day from midnight UTC.

## Sources

- Amazon Location Service, place search for "IIT Bhilai" (run on 24 November 2026 with the project's login): the
  permanent campus at Kutelabhata, 21.2444 N, 81.3176 E.
- Wikimedia Commons, for the photographs: public domain, CC0 or CC BY only, chosen by eye from the 500 px
  renditions; each one's author, licence and page is in `mobile/ASSETS.md`. Five of the fifteen licences were read
  again from the Commons API after the choice was made.
- IETF, RFC 2606, "Reserved Top Level DNS Names" (`.invalid`): https://www.rfc-editor.org/rfc/rfc2606
