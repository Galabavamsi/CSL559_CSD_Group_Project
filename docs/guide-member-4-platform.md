# Member 4 guide: Platform, store network and screens

**Your goal:** everything is secure, observable and demo-ready.
**You own:** `app/modules/serviceability/`, `network_planning/`, `dashboard/`, `app/main.py`,
`app/events.py`, `app/config.py`, everything in `web/`, CI and Docker.
**HLD sections to know well:** 4 Architecture, 5 (services 1 and 10), 8 API and events, 10 Security,
11 Tech stack, 12 Monitoring.

The other three members each build a slice of the warehouse. You build what surrounds all the
slices: who is allowed in, how the store network is laid out, how events leave the system, and how
anyone can see what is going on. You are also the **integrator**: you keep `main` green.

---

## 1. Your part in one minute

| Area | Today | Where the HLD wants it |
| --- | --- | --- |
| Entry point | Every endpoint is open to anyone | A gateway that checks logins and roles |
| Delivery zones | A circle around each store | H3 hexagon cells mapped to stores |
| New-store planning | A report on points you type in | Suggestions from real order locations |
| Events | A database table, handled in-process | A relay that pushes them out (Kafka in the HLD) |
| Visibility | A few counts, polled every 3 seconds | Live dashboard, metrics, alerts |
| Delivery | "Works on my laptop" | CI on every pull request, one-command start |

## 2. Tour of your code

| Function or file | What it does |
| --- | --- |
| `app/main.py` | Builds the app: start-up, error handler, routers, static files |
| `app/events.py` | `publish` writes to `event_log` and calls handlers; `subscribe` registers a handler |
| `app/config.py` | Every tunable number, each overridable by an environment variable |
| `serviceability.distance_km` | Straight-line distance between two points |
| `serviceability.check` | Nearest non-closed store whose radius covers the point, plus an ETA |
| `serviceability.eta_minutes` | Pack time + travel time + a penalty when the store is busy |
| `network_planning.coverage` | For given demand points: which are covered, and one suggested site |
| `dashboard.store_dashboard` | Counts for the ops desk |
| `dashboard.recent_events` | Latest rows from `event_log` |
| `web/index.html`, `styles.css`, `app.js` | The three demo stations. `app.js` has one section per station and a shared `api()` helper |

### Try it by hand

```bash
curl "localhost:8000/v1/serviceability?lat=12.975&lng=77.60"        # served by DS-01 Central
curl "localhost:8000/v1/serviceability?lat=12.80&lng=77.40"         # not serviceable
curl -X POST localhost:8000/v1/network-planning/coverage -H "Content-Type: application/json" \
  -d '{"points":[{"lat":12.972,"lng":77.595,"orders":100},{"lat":12.90,"lng":77.65,"orders":60}]}'
curl "localhost:8000/v1/stores/1/dashboard"
curl "localhost:8000/v1/events?limit=5"
```

Then read `tests/test_serviceability.py` and skim `web/app.js`.

## 3. Ideas you need

**Authentication versus authorisation.** Authentication answers "who are you?" (a login).
Authorisation answers "may you do this?" (a role, and which store you belong to). HLD 10 needs
both: "Staff can act only on their own store".

**JWT.** After login the server gives the client a signed token that says, for example,
`{"sub": "picker1", "role": "picker", "store_id": 1, "exp": ...}`. The client sends it with every
request. The server checks the signature and trusts the contents without a database lookup.
Anyone can *read* a JWT, so never put secrets in it; nobody can *change* one without the signing key.

**H3.** A grid of hexagons covering the Earth, at several sizes. Every location falls in exactly
one cell, and a cell has a short id. If a table maps `cell id -> store id`, "which store serves
this address?" becomes one primary-key lookup instead of measuring the distance to every store.
That is what HLD 11 means by "even-sized hexagons make zone lookups a key match".

**The outbox and "at least once".** `publish` writes the event in the same transaction as the
change that caused it, so an event can never describe something that was rolled back. A separate
**relay** then reads the table and sends events onward. If the relay crashes after sending but
before marking the row as sent, it sends that event again on restart. So consumers must cope with
duplicates, usually by remembering the event id. This is called at-least-once delivery.

**Percentiles.** "p99 ≤ 100 ms" means 99 out of 100 requests finish within 100 ms. Averages hide
the slow requests that users actually notice.

---

## 4. Your tasks

### Milestone 1

#### Task 4.1 (warm-up, do this on Day 0): Repo, CI and Docker

*Why:* nobody else can start until the repository exists, and nobody can merge safely until CI runs.

*Steps*

1. **Create the repository.** The code already has a first commit.
   ```bash
   # after creating an empty private repo on GitHub:
   git remote add origin git@github.com:<you>/darkstore.git
   git push -u origin main
   ```
   Invite the three teammates as collaborators.
2. **Check CI.** `.github/workflows/tests.yml` is already in the repo; open the *Actions* tab and
   confirm the first run is green.
3. **Protect `main`.** In *Settings → Branches*, add a rule for `main`: require a pull request,
   require one approval, and require the `pytest` status check to pass.
4. **Add a Dockerfile:**
   ```dockerfile
   FROM python:3.12-slim
   WORKDIR /srv
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY app app
   COPY web web
   EXPOSE 8000
   CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
5. **Add `docker-compose.yml`:**
   ```yaml
   services:
     app:
       build: .
       ports: ["8000:8000"]
       environment:
         DARKSTORE_DB: sqlite:////data/darkstore.db
       volumes: ["appdata:/data"]
     postgres:                      # used by Member 1 in task 1.7
       image: postgres:16
       profiles: ["postgres"]
       environment:
         POSTGRES_USER: darkstore
         POSTGRES_PASSWORD: darkstore
         POSTGRES_DB: darkstore
       ports: ["5432:5432"]
   volumes:
     appdata: {}
   ```
6. Add the two start commands (`docker compose up --build`, and with `--profile postgres`) to `README.md`.

*Done when*

- A teammate with a fresh clone and Docker gets the demo screens with one command.
- A pull request shows a green check, and a direct push to `main` is refused.

#### Task 4.2: Login and roles

*Why:* HLD 10. Today anyone who can reach the server can write off the whole stock.

*Steps*

1. Add a `Staff` table: `id`, `username` (unique), `password_hash`, `role`, `store_id` (empty for
   city-wide roles). Roles from HLD 10: `picker`, `packer`, `receiver`, `manager`, `ops`, `admin`.
2. Hash passwords with the standard library, never store them as typed:
   ```python
   import hashlib, os, hmac

   def hash_password(password: str) -> str:
       salt = os.urandom(16)
       digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
       return salt.hex() + ":" + digest.hex()

   def check_password(password: str, stored: str) -> bool:
       salt, digest = stored.split(":")
       again = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
       return hmac.compare_digest(again.hex(), digest)
   ```
3. Add `pyjwt` to `requirements.txt`. Add `JWT_SECRET` (from the environment, with a clearly fake
   default such as `"dev-only-change-me"`) and `TOKEN_MINUTES = 30` to `config.py`.
4. Add `POST /v1/auth/login` returning `{"access_token": ..., "role": ..., "store_id": ...}`.
5. Create `app/auth.py`:
   ```python
   def current_staff(authorization: str | None = Header(None)) -> dict:
       """Decode the bearer token or raise 401."""

   def require_role(*roles: str):
       """Dependency: 403 unless the caller has one of these roles (admin always passes)."""

   def check_store(staff: dict, store_id: int) -> None:
       """403 if the caller is tied to a different store."""
   ```
6. Apply them. Agree this table with the team first, then add the dependency to each router
   (each member reviews the change to their own router):

   | Endpoints | Who may call |
   | --- | --- |
   | Serviceability, availability, reservations | Open. In production these are called by the customer app's backend over mutual TLS (HLD 10); say so in the report |
   | Next task, scans, shelf reports, packed, handover | `picker`, `packer` of that store |
   | Goods receipts | `receiver`, `manager` of that store |
   | Stock adjustments, replenishment run, forecasting run, slotting apply, count approval | `manager` of that store |
   | Dashboard, events | Any logged-in staff for their store; `ops` for any store |
   | `/v1/admin/*` | `admin` |

7. Seed staff for both stores (`picker1`, `receiver1`, `manager1`, `ops`, `admin`, ...).
8. **Keep everyone's tests passing.** In `tests/conftest.py`, make the default `client` fixture log
   in as `admin` and send the token on every request, and add a `client_as(role, store_id)` fixture
   for permission tests. Ship this in the same pull request as the protection itself.
9. In `web/app.js`, log each station in as the right seeded user at start-up and pass the token in
   `api()`. Take the picker's name from the token instead of the text box.

*Done when*

- Test: no token on a protected endpoint gives `401`.
- Test: a picker from store 1 asking for store 2's next task gets `403`.
- Test: a receiver posting a stock adjustment gets `403`.
- Test: an expired token gives `401`.
- All existing tests pass unchanged.

*Watch out:* never commit a real secret. Never log tokens or passwords.

### Milestone 2

#### Task 4.3: H3 delivery zones

*Why:* HLD service 1 maps "a customer's H3 cell to its serving store". Circles around stores overlap
and need a distance calculation per store on every request; cells do not.

*Steps*

1. Add `h3` to `requirements.txt`. The library's function names changed between major versions
   (version 4 uses `latlng_to_cell`, `grid_disk`, `cell_to_latlng`), so check the documentation for
   the version you install.
2. Pick a resolution and add it to `config.py` as `H3_RESOLUTION`. Resolution 9 cells are roughly a
   couple of hundred metres across; resolution 8 cells are a few times larger. Look up the exact
   sizes in the H3 resolution table and justify your choice in the report (finer = more accurate
   borders but more rows).
3. Add a `StoreZone` table: `h3_cell` (primary key), `store_id`, `distance_km`.
4. Add `serviceability.rebuild_zones(db)`:
   - for each store, take all cells within enough rings of the store's cell to cover its radius;
   - keep cells whose centre is within `radius_km`;
   - if two stores claim a cell, the nearer store wins.
   Call it from the seed and expose `POST /v1/admin/rebuild-zones`.
5. Rewrite `check`: convert the point to a cell, look that one row up, compute the ETA from the
   stored `distance_km`.
6. **Shrink when busy** (HLD 9.2: "ETA grows or the delivery radius shrinks"): when a store is
   `busy`, serve only cells within 70% of its radius.
7. **Compare with the old method.** Keep `distance_km`. Write a test that checks 1,000 random points
   both ways and asserts they agree except within one cell-width of a zone border. Report the share
   that differ.

*Done when*

- The three existing serviceability tests pass with the new lookup.
- Test: a point in the overlap of two stores always goes to the nearer one.
- Test: a point near the edge is served when the store is open and refused when it is busy.

#### Task 4.4: Network planning from order data

*Why:* FR-12: "Suggest new dark store locations from order heat-maps and coverage gaps". The
prototype only analyses points you hand it.

*Steps*

1. **Record where demand comes from, privately.** HLD 10 says the module "sees an order ID and an
   H3 cell, not a name or phone number". With Member 1, add an optional `h3_cell` to the
   reservation request and table. Have the customer station send the cell of the chosen location.
2. **Record unmet demand.** When `check` answers "not serviceable", save the cell and time in a
   `ServiceabilityMiss` table. People you turned away are the best evidence for a new store.
3. Add `network_planning.heatmap(db, days=30)`: orders per cell and misses per cell.
4. Add `network_planning.suggest_sites(db, k=3)` using greedy maximum coverage:
   - candidate sites = every cell with unmet demand;
   - pick the candidate whose radius would cover the most unmet demand;
   - remove the demand it covers; repeat `k` times;
   - return each site with the demand it would gain.
5. Add `GET /v1/network-planning/heatmap` and `GET /v1/network-planning/suggestions`.
6. Build `web/network.html`: a map (Leaflet from a CDN works without a build step) showing store
   zones, cells coloured by demand, misses in a second colour, and the suggested sites.
7. Write `scripts/generate_demand.py` to create clustered lookups, including one cluster outside
   every zone, so the demo has something to find.
8. Add a `NO_GO_CELLS` list to stand in for the zoning check in HLD 13.2, and skip those candidates.

*Done when*

- Test: with a cluster of misses outside every zone, the first suggestion lies inside that cluster.
- Test: a no-go cell is never suggested.
- The map page shows the gap and the suggestion.

### Milestone 3

#### Task 4.5: Live event feed

*Why:* HLD 8.2 and 9.2. Events reach nobody outside the process today, and the screens poll every
3 seconds.

*Steps*

1. **The relay.** Add `published_at` (empty by default) to `EventLog`. Create a background task that,
   a few times a second, reads unpublished rows in id order, hands each to a list of *sinks*, and
   then sets `published_at`. Start it from `lifespan` beside Member 1's sweeper.
2. **Sink 1: WebSocket.** Add `GET /v1/ws/events?store_id=` as a FastAPI WebSocket endpoint. Keep a
   set of open connections per store in memory; the relay sends each event as JSON to that store's set.
   Remove connections that fail.
3. In `web/app.js`, open the WebSocket and refresh the ops station when an event arrives. Keep the
   3-second polling as a fallback if the socket closes.
4. **Sink 2 (optional): a real broker.** Add a Kafka-compatible broker to Docker Compose under a
   profile, and a sink that produces every event to one topic with `key = store_id`, so events for
   one store stay in order (HLD 8.2). Write `scripts/consume_events.py` that prints what it
   receives: this plays the rider system and the hub.
5. Add an `outbox_lag_seconds` value (age of the oldest unpublished event) to the dashboard. HLD 12
   alerts on "Kafka consumer lag above 30 s"; this is your equivalent.

*Done when*

- Test: publish an event; after one relay pass `published_at` is set and a fake sink received it once.
- Test: if a sink raises an error, the event stays unpublished and is retried on the next pass.
- Holding an item in one browser tab updates the ops desk in another within a second.

*For the report:* the in-process handlers (for example `order.paid` creating the fulfilment job)
still run inside the publisher's transaction. With real microservices, Fulfilment would consume
`order.paid` from Kafka instead, a moment later and possibly twice. That is safe here because
`create_job` returns the existing job for a repeated `order_id`. Point that out; it shows you
understand what the move to Kafka would demand.

#### Task 4.6: Ops dashboard page

*Why:* FR-13, and HLD 12's KPI table deserves a screen that shows each KPI next to its target.

*Steps*

1. Add `GET /v1/dashboard/overview`: one row per store (status, waiting orders, low-stock count) for
   a city-wide view.
2. Extend `dashboard/service.py` to gather, by calling the other modules' **functions** (never their
   tables): Member 2's `fulfilment.metrics` and attention list, Member 3's `replenishment.kpis`,
   Member 1's inventory accuracy and near-expiry report.
3. Build `web/ops.html`:
   - at the top, anything needing action now: stalled orders, bags waiting for a rider, stock-outs;
   - then each KPI with its measured value, its HLD target, and a clear met / not met mark;
   - orders per hour as a simple bar chart;
   - the live event feed from task 4.5.
4. Design it to be read from across a room: large numbers, few colours, problems first.

*Done when*

- Every KPI in HLD 12 that the team has implemented appears with its target.
- A teammate's metric missing or erroring shows as "not available", and the rest of the page still loads.

### Milestone 4

#### Task 4.7: Monitoring

*Why:* HLD 12, "Technical monitoring".

*Steps*

1. Add `prometheus-client` and expose `GET /metrics`.
2. Add middleware that times every request into a histogram labelled by method, route template and
   status code. Use the route template (`/v1/stores/{store_id}/availability`), not the raw path, or
   you get one series per store.
3. Add counters where they matter: reservations by result (`held`, `insufficient_stock`), events
   published by type, scans by result (`match`, `mismatch`).
4. Add gauges: holds in progress, `outbox_lag_seconds`.
5. Add request ids: accept or create an `X-Request-ID`, return it in the response, and include it in
   every log line for that request. Log in JSON.
6. Write the alert rules as a table in the report, one per alert in HLD 12:

   | Alert | Metric | Fires when |
   | --- | --- | --- |
   | Spike in failed reservations | reservations by result | failure share over 5 minutes is above your chosen threshold |
   | Event lag | `outbox_lag_seconds` | above 30 s |
   | Cache and database disagree | Member 1's audit | any mismatch |
   | Store offline | time since a store's last event | above your chosen threshold during opening hours |

7. *Optional:* add Prometheus and Grafana to Docker Compose and include one dashboard screenshot.
8. *Optional:* a simple rate limit on the open customer endpoints (for example 20 requests a second
   per client), answering `429`. This is the last gateway duty from HLD 5 still missing.

*Done when*

- `/metrics` shows the latency histogram after a few requests.
- Test: a response carries the `X-Request-ID` it was sent.

#### Task 4.8: Integration, load test and final demo

*Why:* four people's work has to arrive as one system.

*Steps*

1. **Load test** (with Member 1, their task 1.8). Write a script that sends a realistic mix for one
   minute, about 90% availability and serviceability reads, 8% holds, 2% payments, and reports p50
   and p99 per endpoint. Compare the read p99 with the HLD target of 100 ms, with Member 1's cache
   off and on. A laptop is not a production cluster, so say that plainly beside the numbers.
2. **End-to-end test.** Add `tests/test_end_to_end.py` that walks the whole demo script through the
   API with real logins: order, pay, pick with one wrong scan and one empty shelf, pack, hand over,
   reorder, receive, forecast, and a final stock audit.
3. **Update the documents.** In `README.md`, move every finished feature out of the "Simplified for
   now" column. Update `DEMO_SCRIPT.md` with each member's new feature.
4. **Rehearse** the demo twice from a fresh clone, on the laptop you will present from, with the
   network off. (The screens load two web fonts from the internet and fall back to system fonts
   without it; decide which look you want and test that one.)
5. Tag the release: `git tag v1.0 && git push --tags`.

*Done when*

- A fresh clone, one command, and the full demo script works.
- The end-to-end test is green in CI.

---

## 5. What others need from you

| Who | Needs | When |
| --- | --- | --- |
| Everyone | The repository, CI and branch protection | Day 0 |
| Everyone | `require_role`, `check_store`, and a logged-in test client that keeps their tests passing | Milestone 1 |
| Everyone | `events.publish` and `subscribe` to keep their signatures | Always |
| Member 1 | The Postgres service in Docker Compose (their task 1.7); help with the load script (1.8) | Milestones 1 and 4 |
| Members 1 and 2 | A place in `lifespan` to start background loops | Milestone 1 |
| Members 1, 2, 3 | A slot on the dashboard for each KPI they produce, and the response shape you expect | Milestone 3 |
| Member 2 | `serviceability` to keep honouring `Store.status == "busy"` | Always |

As integrator: when `main` goes red, find the merge that did it and ask its author to fix or revert
it the same day. Do not fix other people's modules yourself; you will have no time left for your own.

## 6. What to show at the final demo

1. A picker from store 1 trying to act in store 2: refused.
2. The map: delivery zones, a gap with unmet demand, and the suggested new site.
3. Two browser windows: an action in one appears in the other instantly.
4. The KPI page with targets, and the load-test table.

## 7. If you have time left

- Deploy the Docker image to a free hosting tier so the demo has a public link. Check the host's
  current limits before relying on it.
- An audit log of who called which protected endpoint.
- Dark-store "edge node" experiment (HLD 5): a second copy of the app that queues events while the
  first is unreachable, then replays them. Even a design note with a diagram is worth including.
