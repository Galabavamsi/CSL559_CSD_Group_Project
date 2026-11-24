# Engineering journal

Notes written while the work happens: what was decided, what went wrong, how it was fixed and where the facts came
from. They are raw material for the report, the documentation and blog posts, so each entry stands on its own.

## How an entry is written

- One Markdown file per topic, named `YYYY-MM-DD-short-title.md`.
- Sections, in this order: **Context**, **What happened** or **Decision**, **Why**, **What it cost or leaves open**,
  **Sources**.
- A fact that comes from outside the project (a manual, a vendor page, a paper) gets a link under **Sources**. A fact
  we measured ourselves says how it was measured.
- No account numbers, server ids, addresses or secrets: this repository is public.

## Entries

| Date | Entry | In one line |
| --- | --- | --- |
| 2026-11-23 | [PostgreSQL with PostGIS only, and two cities](2026-11-23-postgresql-postgis-only.md) | SQLite removed; hub locations are PostGIS points; Bangalore and Bhilai |
| 2026-11-23 | [CI failed on tables we never created](2026-11-23-ci-tiger-search-path.md) | The PostGIS image's geocoder tables looked like ours; fixed with the search path |
| 2026-11-23 | [AWS groundwork](2026-11-23-aws-groundwork.md) | Sign-in, cost guard, DNS, certificates, email and a dev server before any app code |
| 2026-11-23 | [Customers buy fixed packs; farmers deliver kilograms](2026-11-23-fixed-packs.md) | A departure from the HLD: stock stays in whole units, and kg become units at putaway |
| 2026-11-23 | [Accounts: signing in with a code sent by email](2026-11-23-accounts-and-email-codes.md) | No passwords; the rules each code follows and where they come from; a hole it closed |
| 2026-11-23 | [Farm supply: from a farmer's listing to units on a shelf](2026-11-23-farm-supply.md) | HLD flow A: hub choice, drop slot, weighing and grading, kg into units; a fault the tests caught |
| 2026-11-23 | [The phone app, first cut](2026-11-23-the-phone-app.md) | One Expo app for three roles; a mock and the real API behind one interface; what was and was not checked |
| 2026-11-23 | [Recording the demo, and what the recording found](2026-11-23-recording-the-demo.md) | A script records the real backend end to end; the handbook and video come from it; Bhilai turns out to have no hub |
| 2026-11-24 | [An app that installs, and a demo one person can run](2026-11-24-an-app-on-the-phone-and-a-demo-by-one-person.md) | An APK built on our own server; a hub that picks and packs by itself on staging; a setting that nearly shipped unreviewed |
| 2026-11-24 | [An order reaches a door: agents, trips and a four-digit code](2026-11-24-an-order-reaches-a-door.md) | Trips formed inside the packing transaction; a code worked out and never stored; the sweep that sent an agent out with one bag |
| 2026-11-24 | [Shops that are never empty, a hub at IIT Bhilai, asking for delivery, and India's calendar](2026-11-24-stocked-shops-iit-bhilai-and-asking-for-delivery.md) | Demo farms deliver through the ordinary intake; a request for delivery counts in planning; a date fault found at one in the morning |
| 2026-11-24 | [The app moves onto the server, a price that could rise unseen, and a key for map tiles](2026-11-24-the-app-on-the-servers-orders-and-a-map-key.md) | The checkout shows the hub's bill and a dearer one is refused; a tiles-only key, tested by drawing Bhilai |
| 2026-11-24 | [Orders on the server, the shop's batch facts, and a design written down](2026-11-24-orders-on-the-server.md) | An order written inside the hold's confirmation and priced from the pick tasks; a rescue price per batch; a migration changed after it ran |
| 2026-11-23 | [Bhilai gets hubs, the hub gets an intake screen, and the app meets a real phone](2026-11-23-bhilai-hubs-intake-and-a-real-phone.md) | Opening a hub in one transaction; the receiver's screen; a keyboard fault only a phone could show |
| 2026-11-23 | [The tests move to AWS](2026-11-23-ci-moves-to-aws.md) | GitHub stopped running checks; CodeBuild runs them; a deploy waits for them; a flaw the checking found |
| 2026-11-23 | [Staging on AWS](2026-11-23-staging-on-aws.md) | First run on AWS; a password that would have expired before the demo; a forced failover; real prices |
