# The phone app

One app for customers, farmers and delivery agents: Expo SDK 58, React Native 0.88, TypeScript and Expo Router. A
person signs in with an email address and a six-digit code, and the account's role decides which part of the app
they see. It runs on Android, in Expo Go while you work on it or as an installed build, and in a browser as a web
build.

## Install it on a phone, with no laptop

An installable Android build with staging's address built in is on the
[release page of 24 November](https://github.com/Galabavamsi/CSL559_CSD_Group_Project/releases/tag/app-staging-2026-11-24).
Open the link on the phone, download the APK, allow the browser to install apps when Android asks, and open
**Farm2Home**. It is signed with a debug key and its Android name is `com.galabavamsi.farm2home`. Some networks
block the staging address and the app then says "No connection": use mobile data. To show it,
[`docs/DEMO_ON_A_PHONE.md`](../docs/DEMO_ON_A_PHONE.md) is the run sheet.

## Run it while you work on it

You need Node.js (the dev server and the Android build use Node 22). In this folder:

```bash
npm install
npx expo start                # built-in demo data; scan the QR code with Expo Go, or press w for a browser
```

On Windows, in PowerShell, type `npm.cmd` and `npx.cmd` in place of `npm` and `npx`.

The app chooses its backend once, at start-up (`src/config.ts`, `src/api/index.ts`):

| `EXPO_PUBLIC_API_URL` | What the app talks to | Signing in |
| --- | --- | --- |
| not set | Built-in demo data for Bhilai and Bangalore, in memory. Nothing leaves the device | Any email address; the code is `123456` |
| set | That API | A real code is emailed. A local API writes it to its own output instead (`EMAIL_BACKEND=log`) |

Set it for one run, or put it in `.env.local` (copy `.env.example`, which points at staging):

```powershell
$env:EXPO_PUBLIC_API_URL = "https://staging.farm2home.galabavamsi.com"; npx.cmd expo start --clear
```

```bash
EXPO_PUBLIC_API_URL=https://staging.farm2home.galabavamsi.com npx expo start --clear
```

`--clear` matters after changing the variable: Expo writes it into the bundle. Two more settings work on demo data
only: `EXPO_PUBLIC_MOCK_HOLD_SECONDS` (600) and `EXPO_PUBLIC_MOCK_ORDER_STEP_SECONDS` (12), to watch a hold run out
or an order move faster.

**Against an API on your own machine.** Start the API so the phone can reach it (`--host 0.0.0.0`; by default it
listens to this machine only), then give the app this machine's address on the network:

```bash
python -m uvicorn app.main:app --host 0.0.0.0                                   # in the repository's folder
EXPO_PUBLIC_API_URL=http://<this machine's address>:8000 npx expo start --clear  # in mobile/
```

### In Expo Go, over Wi-Fi

Install Expo Go (the version for SDK 58) on an Android phone, put the phone and the computer on the same network,
and scan the QR code `npx expo start` prints. On Windows, a Wi-Fi network marked "Public" stops the phone reaching
the computer until Node is allowed through the firewall; a hotspot from the phone is the simplest shared network.

### In Expo Go, over a USB cable

With USB debugging on and Android's platform tools (`adb`) on the computer, the cable carries the bundle and the
phone can stay on mobile data, which reaches staging where some Wi-Fi does not:

```bash
npx expo start --localhost --port 8081
adb reverse tcp:8081 tcp:8081
adb shell am start -a android.intent.action.VIEW -d exp://127.0.0.1:8081 host.exp.exponent
```

For an API on the same computer, also run `adb reverse tcp:8000 tcp:8000` and start Expo with
`EXPO_PUBLIC_API_URL=http://127.0.0.1:8000`. Unplugging the cable ends both `adb reverse` links; run them again.
In Expo Go, keys typed while no text field has focus are read as developer shortcuts and can close the app.

### In a browser

`npx expo start --web` while you work. For the built pages:

```bash
npm run export:web            # static web build in dist/
npx expo serve --port 8090    # serve dist/; open http://localhost:8090/
```

The web export is a single page. `expo serve` has no fallback for it, so start at `/`; reloading on a sub-page gives
a 404 there. A real host needs the usual "send every path to index.html" rule.

## Checks

```bash
npx tsc --noEmit              # the type-check; npm run typecheck is the same
```

Run it before every pull request that touches `mobile/`. The test run on AWS (`infra\test.ps1`) runs it too, after
`npm ci`, and fails the commit if it fails.

## Build the Android app

On the dev server, which has Java 17 and the Android SDK ([`infra/README.md`](../infra/README.md) says how to reach
it), from the repository's folder:

```bash
API_URL=https://staging.farm2home.galabavamsi.com bash scripts/build_apk.sh
```

Expo generates the Android project from `app.json` (`expo prebuild`, into `mobile/android`, which git ignores), and
Gradle builds a release for 64-bit ARM phones, signed with the debug key of Expo's generated project. The API's
address is built in. The result is `mobile/android/app/build/outputs/apk/release/app-release.apk`. The first build
takes about eleven minutes, later ones a few.

To get it off the dev server, copy it through the private artifacts bucket (`aws s3 cp`). To put it on a phone over
the cable, `adb install -r <the apk>`. To hand it out, attach it to a release on GitHub:
`gh release create <tag> <the apk>`; the 24 November one is `app-staging-2026-11-24`. Every build is signed with the
same debug key, so a phone that has one installed takes a newer one as an update.

## How it is built

| Path | What is there |
| --- | --- |
| `src/app/` | The screens, one file per route (Expo Router). `index.tsx` sends each person to their part by role. `(auth)/`: email, then code. `(customer)/`: the tabs (home, orders, profile), delivery location, product, cart, checkout and an order's page. `farmer/`: home, add a farm, list produce. `agent/`: the agent's screen (hub, duty, bags, stops). `account.tsx`: the profile for farmers and agents |
| `src/api/` | `client.ts` is the one interface, `ApiClient`. Two implementations: `http.ts`, the real API (it maps each answer to the app's types and renews the session when a call is refused with 401), and `mock/`, the demo data. `index.ts` picks one at start-up. `queries.ts` holds the TanStack Query hooks, the only way screens read or write. `types.ts` and `errors.ts` (`ApiError`) |
| `src/state/` | Small Zustand stores: `session` (kept in secure storage: the Android Keystore through `expo-secure-store`, `localStorage` on the web build), `cart` (with the hold being paid for), `deliveryLocation`, `preferences` (the theme) and `pendingSignIn` (in memory only). Each kept store's name carries the backend it belongs to, so a sign-in or cart made on demo data is never sent to a server, nor one server's to another |
| `src/features/` | Logic and parts of screens that belong to one area: `cart`, `catalogue` (aisles, freshness labels, photographs), `delivery` (the agent's screen), `location` (the area picker and the preset areas per city), `orders`, `profile` |
| `src/components/` | Shared UI: buttons, cards, the product card and its picture, the order's steps, the code input; the logo in `brand/` |
| `src/theme/` | The Material Design 3 theme for react-native-paper: colours (light and dark), type, spacing |
| `src/lib/` | Plain helpers: dates, money, the bill, distances, ids, secure storage |
| `src/config.ts` | The settings read at start-up |
| `assets/images/` | The icon, the Android icon layers, the splash image and the favicon, drawn from the logo by `scripts/make-icons.mjs` (`npm run icons`) |
| `assets/produce/` | The photographs (next section) |

**To add a call to the backend:** add the method to `ApiClient` in `src/api/client.ts`, write it in `http.ts` and in
`mock/client.ts`, and add a hook in `queries.ts`. The type-check fails until both implementations have it. Keep the
demo data close to what the server answers, since screens are often checked on it first.

## Photographs and credits

`assets/produce/` holds 40 photographs, one for each kind of produce and each packaged item: openly licensed files
from Wikimedia Commons (public domain, CC0 and CC BY), resized to 500 px wide. `src/features/catalogue/photos.ts`
matches a product to its photograph by name. Each photograph's author, licence and source page are in
`assets/produce/credits.json` and in [`ASSETS.md`](ASSETS.md), which also lists the fonts, icons and libraries used
for the look and their licences. The CC BY photographs must be credited: `ASSETS.md` is that credit today, and the
product pages should show it before a public release.

## Known limits

- **No map.** A customer's location is the phone's GPS fix or an area picked from a list
  (`src/features/location/presetAreas.ts`); a farm's is a GPS fix good to 50 m. The map goes in at one place,
  `src/features/location/LocationPicker.tsx`. `docs/DESIGN.md` section 1 has the plan.
- **No agent's position, no time of arrival, no push notifications, nothing in the background.** Each needs native
  code or permissions the app does not have yet.
- **A bag is confirmed by a tap,** not by scanning its label.
- **Signed with the debug key,** which every Expo project shares. Fine for installing by hand; a store release
  needs its own key, and phones with this build would have to uninstall it first.
- **The API's address is built in.** A build for staging talks only to staging.
- **A photograph per kind of item,** not of the batch being sold.
- **Not yet tried from the installed build,** as of 24 November: signing in and ordering end to end. The same code
  has been exercised behind those screens in the web build.
