# Farm2Home mobile app

One Expo app (SDK 58, TypeScript, Expo Router) for customers, farmers and delivery agents. It runs in Expo Go on
Android and as a web build.

## Run it

```bash
npm install
npx expo start            # scan the QR code with Expo Go on an Android phone (same Wi-Fi as this computer)
npx expo start --web      # or open it in a browser
```

The app picks its backend once, at start-up:

| `EXPO_PUBLIC_API_URL` | Mode | What happens |
| --- | --- | --- |
| not set | mock | Built-in demo data for Bhilai and Bangalore. Any email signs in; the code is `123456`. Nothing leaves the device. |
| set | http | Talks to that API. A real code is emailed to you. |

Set it for one run, or put it in `.env.local` (see `.env.example`):

```powershell
$env:EXPO_PUBLIC_API_URL = "https://staging.farm2home.galabavamsi.com"; npx expo start --clear
```

```bash
EXPO_PUBLIC_API_URL=https://staging.farm2home.galabavamsi.com npx expo start --clear
```

`--clear` matters after changing the variable: Expo writes it into the bundle.

## Checks

```bash
npm run typecheck         # tsc --noEmit
npm run export:web        # static web build in dist/
npx expo serve --port 8090   # serve dist/ locally; open http://localhost:8090/
```

The web export is a single page. `expo serve` has no fallback for it, so start at `/`; reloading on a sub-page
gives a 404 there. A real host needs the usual "send every path to index.html" rule.

## Where things are

| Path | What |
| --- | --- |
| `src/app/` | Screens, one file per route (Expo Router). `(auth)`, `(customer)`, `farmer`, `agent`. |
| `src/api/` | `client.ts` is the one interface; `http.ts` (real API) and `mock/` (demo data) implement it; `queries.ts` has the TanStack Query hooks screens use. |
| `src/state/` | Small Zustand stores: session (secure storage), cart, delivery location, preferences. |
| `src/theme/` | Material Design 3 theme for react-native-paper: colours, type scale, spacing. |
| `src/components/` | Shared UI, including the logo in `brand/`. |
| `src/features/` | Logic and UI that belong to one area: catalogue, cart, location, orders, profile. |
| `src/lib/` | Pure helpers: dates, money, the bill, ids. |
| `scripts/make-icons.mjs` | Redraws the app icons from the logo's shapes (`npm run icons`). |

The map goes in at one place: `src/features/location/LocationPicker.tsx`.

What every font, icon and library used for the look is, and its licence: [ASSETS.md](ASSETS.md).
