# PostgreSQL with PostGIS only, and two cities

*23 November 2026. First change of the rebuild into JustInTimeFarm2Home.*

## Context

The dark-store prototype ran on SQLite by default and on PostgreSQL when asked, and every test ran on both. The
JustInTimeFarm2Home design (HLD section 8) asks for three queries: the nearest hub to a farm, the hubs that deliver
to a customer, and a stock reservation that cannot oversell. The first two are geographic.

## Decision

1. PostgreSQL with the PostGIS extension is the only database. SQLite is removed from the app, the tests, CI and
   Docker Compose.
2. Every hub belongs to a city. Two cities are seeded: Bangalore (tier 1) and Bhilai (tier 2).
3. A hub's position is still entered as `lat` and `lng`, and PostgreSQL derives a `location` point from them as a
   stored generated column, with a GiST index.
4. Two queries are answered by PostGIS: `nearest_store` and `stores_covering` in
   `app/modules/serviceability/service.py`.

## Why

**One database instead of two.** "Nearest hub" and "within radius" have no SQLite form, so keeping SQLite meant a
second, approximate code path for every geographic query, tested but never used in the demo.

**geography, not geometry.** The geography type measures along the earth's surface and gives metres, so a radius is
written as `3000` and means 3 km anywhere. With geometry in latitude and longitude the unit would be degrees, which
are not the same length east-west as north-south.

**A generated column.** If the application wrote both `lat`/`lng` and a point, some code path would sooner or later
update one and not the other. A column the database computes cannot disagree with its inputs. A test changes a hub's
`lat` and `lng` and reads the point back.

**Nearest hub with `<->`.** `ORDER BY location <-> point LIMIT 1` walks the GiST index outwards from the point
instead of measuring the distance to every hub. For geography the operator orders by distance on a sphere, not on
the spheroid; the distance we report is computed separately with `ST_Distance`.

**Covering hubs with two `ST_DWithin` conditions.** Each hub has its own service radius. The PostGIS manual notes
that the index cannot be used when the distance differs per row, and advises adding a second condition with one
distance for all rows. We checked this ourselves by asking PostgreSQL for its plan with sequential scans switched off
(`SET enable_seqscan = off`, then `EXPLAIN`):

| Query | Plan |
| --- | --- |
| `ORDER BY location <-> point LIMIT 1` | Index Scan on `ix_stores_location`, ordered by `<->` |
| `ST_DWithin(location, point, radius_km * 1000)` alone | Seq Scan: the index cannot be used at all |
| `ST_DWithin(location, point, 15000)` and the per-row condition | Index Scan, `location && _st_expand(point, 15000)` |
| `ST_DWithin(location, point, (SELECT max(radius_km) FROM stores) * 1000)` and the per-row condition | Index Scan, with the subquery computed once |

The first draft used the third form with a configured maximum radius. That left a trap: a hub given a larger radius
than the setting would be cut off silently. The fourth form has no setting. It takes the largest radius any hub has,
which PostgreSQL works out once per query, so the index narrows the hubs down and each hub's own radius is applied
after.

**Two cities.** A tier-2 and a tier-1 city show the same design at two sizes: Bhilai at the HLD's pilot numbers
(3 km radius, as the Blinkit tier-2 store in HLD section 3) and Bangalore denser, with a 2 km radius.
The Bangalore radius is our assumption, not a measured figure.

## What it cost or leaves open

- The app no longer starts with zero setup: it needs a PostgreSQL server. `docker compose up -d postgres` gives one.
- The experiment scripts used to work on a temporary SQLite file. They now create a throwaway database beside the
  app's and drop it at exit (`scripts/scratch.py`). The database login therefore needs the right to create databases.
- The test suite (610 tests) took about four and a half minutes on the dev server, all of it on PostgreSQL. Emptying
  tables with `TRUNCATE` instead of dropping and creating them did not make it faster. The time was going to the
  disk: every test commits many times, and each commit waited for the server's network disk to confirm the write.
  With `fsync`, `synchronous_commit` and `full_page_writes` switched off on the test database, the same suite takes
  2 min 9 s. Those settings are for a throwaway test database only: a crash can corrupt it. GitHub's CI machines,
  with local disks, already ran the suite in under three minutes.
- The H3 delivery-zone lookup is unchanged. Serviceability still answers from the zone table; the PostGIS queries sit
  beside it and are used for the "nearest hub" in a not-serviceable answer.
- Bhilai has no hubs yet. They come from hub placement.
- On Amazon RDS the PostGIS extension must be created by a role with `rds_superuser`; the app runs
  `CREATE EXTENSION IF NOT EXISTS postgis` at start, so the app's database user needs that on first start.

## Sources

- PostGIS manual, `ST_DWithin` (geography signature, `use_spheroid`, index use, and the note on a radius that varies
  per row): https://postgis.net/docs/ST_DWithin.html
- PostGIS manual, `<->` distance operator (index-assisted nearest neighbour; sphere distance for geography):
  https://postgis.net/docs/geometry_distance_knn.html
- PostGIS workshop, "Nearest-Neighbour Searching": https://postgis.net/workshops/postgis-intro/knn.html
- AWS, "Managing spatial data with the PostGIS extension" (RDS for PostgreSQL, `rds_superuser`):
  https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.PostGIS.html
- Our own measurements, on PostgreSQL 16 with PostGIS 3.4 on a 4 vCPU server: the query plans in the table above
  (two hubs in the table, sequential scans switched off so the plan shows what the index can do, not what is
  cheapest for two rows), and the full suite: 610 passed in 4 min 28 s with default durability settings and in
  2 min 9 s with disk syncing off.
