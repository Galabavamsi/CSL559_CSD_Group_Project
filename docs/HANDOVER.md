# Handover

*Written 24 November 2026 for whoever picks this up next, including its owner a week from now. It says where
things stand, where they are, how to do the things that will need doing, and what is known to be wrong. Reasons
for decisions are in `docs/DESIGN.md`; how each piece came to be is in `docs/journal/`.*

## What this is

JustInTimeFarm2Home moves produce from farms to homes through small local hubs. A farmer lists a lot, the nearest
hub with room weighs and grades it and packs it into units, a customer nearby buys from that hub's shelves, and a
delivery agent carries several neighbours' orders in one trip. It is a FastAPI backend with a PostgreSQL database
on AWS, web pages for the hub's staff, and one phone app for customers, farmers and delivery agents.

It grew out of a university group project (CSL559), a dark-store prototype whose stock and picking code is still
the base. The live demo is on 3 and 4 December 2026 in Bhilai.

## Where things stand

**Works end to end, on staging, today.**

| Step | Who | Where |
| --- | --- | --- |
| List a lot; see the hub's grade | Farmer | Phone app |
| Take the lot in: weigh, grade, pack, put away | Hub receiver | `/intake.html` |
| Shop from the hub that serves an address; hold the cart; pay (a stand-in) | Customer | Phone app |
| Pick oldest batch first, scan, pack into a crate slot | Hub picker | `/picker.html` |
| Take a trip, check the bags out, hand over against the customer's code | Delivery agent | Phone app |
| Follow the order to Delivered | Customer | Phone app |
| Watch stock, orders, demand and where to open the next hub | Hub and city staff | `/`, `/ops.html`, `/network.html` |

**Numbers.** 800 automated tests pass. Two cities: Bangalore (2 hubs) and Bhilai (4 hubs, one at IIT Bhilai).
The measured numbers and how each was taken are in the report, `docs/handbook/`.

**Not built.** A map in the app and the agent's position; a time of arrival; real payment; what the hub does with
a bag that comes back undelivered; releasing a door code locked by wrong tries; hubs asking farms for what they
expect to sell; the day-long simulation that would say when pooling pays. `docs/DESIGN.md` sections 4.10 and 6
say why each was left.

## Where things are

| Path | What it holds |
| --- | --- |
| `app/` | The backend. One folder per module under `app/modules/`, each with `service.py` (the rules) and `router.py` (the HTTP face). `app/demo_supply.py` and `app/demo_hub.py` are the demo's stand-ins for farmers and pickers |
| `migrations/` | Database changes, 0001 to 0009. Once one has run on staging, add a new one; do not edit it |
| `tests/` | The tests. They need PostgreSQL with PostGIS, so they run on AWS, not on a laptop |
| `mobile/` | The phone app (Expo, React Native). `src/api/` has two implementations of one interface: the real API and built-in demo data |
| `web/` | The hub's pages, plain HTML and JavaScript, served by the backend |
| `infra/` | CloudFormation templates and the three scripts that test, deploy and smoke-test |
| `scripts/` | Load tests, comparisons, the demo recorder, the app build |
| `docs/DESIGN.md` | Every decision with its reason, what was considered and what it costs |
| `docs/journal/` | One entry per piece of work: what was built, what went wrong, sources |
| `docs/DEMO_ON_A_PHONE.md` | The run sheet for showing it from phones |
| `docs/handbook/` | The report: system design, pictures, measurements |

## How to

Commands are for PowerShell on Windows, from the repository's folder, with the AWS CLI and the GitHub CLI signed
in. `infra/README.md` has the longer version of the first three.

**Test a commit.** Runs the whole suite on AWS and marks the commit on GitHub. About five minutes.

```powershell
infra\test.ps1 -Ref some-branch
```

**Deploy to staging.** Tests the commit if it has not passed, builds the image, updates the service. About
fifteen minutes. It ends with a health check that fails from a network that blocks the staging address; that
line alone does not mean the deploy failed.

```powershell
infra\deploy.ps1 -Env staging -Ref main
```

**Check staging afterwards.** From a machine that can reach it (the dev server can):

```bash
bash infra/smoke.sh https://staging.farm2home.galabavamsi.com
```

**Build the phone app.** On the dev server, which has Java 17 and the Android SDK. The first build takes about
eleven minutes, later ones a few.

```bash
API_URL=https://staging.farm2home.galabavamsi.com bash scripts/build_apk.sh
```

The result is `mobile/android/app/build/outputs/apk/release/app-release.apk`. To hand it out, attach it to a
release on GitHub (`gh release create <tag> <file>`); the release of 24 November is `app-staging-2026-11-24`.
A phone that has that build installed takes a newer one as an update: every build is signed with the same
debug key, the one Expo's generated Android project carries.

**Run the app while changing it.** In `mobile/`: `npx expo start`. With no `EXPO_PUBLIC_API_URL` it runs on
built-in demo data (any email, code 123456); with it set, against that API.

**Record the whole flow as a check.** On the dev server, `bash scripts/record_demo.sh` starts the backend on an
empty database, builds the app for the web, and drives nine passes through it with a real browser, from a
farmer's listing to the customer's door. It is the nearest thing to an end-to-end test and has caught faults the
unit tests could not. About ten minutes. It also remakes the report's screenshots.

**Stock the shops now.** Staging does this by itself every half hour. To force it, as an admin:
`POST /v1/admin/demo-supply`.

**Make a delivery agent's account** (staging lets anyone sign up as one; elsewhere an admin does it):
`POST /v1/admin/agents` with an email address, a name and the hub's id.

## Access

No secret is written in this repository, which is public, and none is written here.

| Thing | Where it is |
| --- | --- |
| Staging | `https://staging.farm2home.galabavamsi.com`; API description at `/docs` |
| AWS | One account, region Mumbai (`ap-south-1`). Everything of this project is tagged `Project=farm2home`; the account holds other projects, which are not to be touched. Stacks: `farm2home-network`, `-build`, `-ci`, `-data-staging`, `-app-staging` |
| Staff logins on staging | `picker<hub id>`, `packer<hub id>`, `receiver<hub id>`, `manager<hub id>`, and the city-wide `ops` and `admin`. One shared password, in Secrets Manager under `farm2home/staging/staff-password` |
| App sign-in | A six-digit code emailed to the address. Mail is sent through Amazon SES from the project's domain |
| The dev server | An EC2 machine named `farm2home-dev-server`, reached only through Systems Manager (no SSH key exists). It runs the tests' database, the demo recorder and the app build. It costs about 0.20 US dollars an hour while running: stop it when work pauses for days |
| Built files | A private S3 bucket named `farm2home-artifacts-<account id>`, emptied after 30 days |
| Map tiles | An Amazon Location API key named `farm2home-map-tiles`: tiles only, ends 31 March 2027. Nothing uses it yet |
| The phone app's Android name | `com.galabavamsi.farm2home`, signed with the debug key in Expo's generated project |

The laptop's AWS sign-in (`aws login`) is a session that ends after some hours. A deploy that stops with "Your
session has expired" has changed nothing; sign in and run it again.

## What staging pretends

A demo by one person has no farmer, no picker and no time to wait. Four settings in `infra/app.yml` stand in for
them. They simulate people; the records are made by the real code paths. All are off by default.

| Setting | Stands in for |
| --- | --- |
| `DEMO_SUPPLY` | Farmers: lots arrive through the hub's ordinary intake when a hub is nearly out of an item |
| `DEMO_AUTOPACK` | Pickers: an order nobody starts within 45 seconds is picked and packed |
| `POOL_MAX_WAIT_MINUTES=0.5` | Waiting: a lone packed order leaves after half a minute, not ten |
| `AGENT_SELF_SIGNUP` | The platform team: anyone may sign in as a delivery agent |

## Known faults and risks

- **Some networks block the staging address.** The owner's campus Wi-Fi and the development laptop's network both
  do; the app then says "No connection". Mobile data works. For the demo this is the largest risk: rehearse on
  the venue's network. A fix would be to serve the API from an address such filters know, such as a CloudFront
  one.
- **A target is missed.** Availability answers in 130 ms at the 99th percentile under load; the target is 100 ms.
- **Signing in and ordering from the installed app had not been tried** when this was written, only its first
  screen. Everything behind it has been exercised through the web build of the same code.
- **Distances are straight lines times 1.7.** The order of a trip's stops is right for a few addresses; its
  kilometres are an estimate. Bhilai's railway line makes real routes longer than that in places.
- **A locked door code can only end in "not delivered"**, and nothing at the hub handles the bag that returns.
- **Sales statistics count a day from midnight UTC**, 05:30 in India. Use-by dates and the rescue price use
  India's date.
- **Tests are not started by a push.** The AWS connector for GitHub has not been given access to this
  repository, so `infra\test.ps1` is run by hand. `infra/README.md` has the steps.
- **The app is signed with a debug key**, which is the same for every Expo project and known to everyone. That
  is fine for installing by hand and wrong for a store: a store release needs its own key, and phones with this
  build would have to uninstall it first.
- **Hub staff share one password per environment.**
- **The report's video is from 23 November** and stops at Packed.

## What to do next, in order

1. **Rehearse on phones, on the venue's kind of network.** `docs/DEMO_ON_A_PHONE.md`. Two phones if possible.
   Fix only what the rehearsal finds.
2. **Decide about the blocked address** (first fault above) before 3 December.
3. **The bag that comes back**, and releasing a locked code: the hub's half of a failed delivery (design 4.7).
4. **The dispatch panel as a page** for the hub: the API exists (`GET /v1/stores/{id}/dispatch`).
5. **A map in the app**, with the tiles key: the customer's pin, the agent's stops (design 1.2).
6. **Road times** for the order of stops and for a time of arrival.
7. **The simulated day** (design 8): the one measurement that would say whether pooling pays, and at what order
   rate.
8. **Hubs asking farms** for what they expect to sell (design 5).

## Before the demo on 3 December

- Deploy nothing new after the last rehearsal.
- Check `GET /v1/stores/6/shop` lists a dozen items an hour before; if not, `POST /v1/admin/demo-supply`.
- Have the staff password to hand for the hub's pages, and both phones signed in.
- Sign in to AWS on the laptop that morning, in case something has to be restarted.
- Bring a mobile hotspot.
