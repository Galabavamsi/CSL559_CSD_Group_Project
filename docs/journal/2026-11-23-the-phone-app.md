# The phone app, first cut

*23 November 2026. One app for customers, farmers and delivery agents, built beside the backend it talks to.*

## Context

The HLD names an Expo React Native app for the phone (HLD 15). Nothing existed: the prototype had three plain HTML
pages. The backend it needs was being built at the same time, and half of it (customer orders, delivery) does not
exist yet. The development laptop cannot build an Android app: no Android SDK, and a security policy that blocks
some unsigned programs.

## Decisions, and why

**One app, three roles.** The role of the account decides the home screen after sign-in. Three apps would be three
builds and three installs for one demo.

**Expo Go for development.** The app is plain JavaScript on top of Expo's own modules, so the phone runs it inside
Expo Go and the laptop only serves the bundle. Nothing native is built until a release. This is what made the
laptop's limits not matter: the toolchain installed and bundled with nothing blocked.

**One client interface, two implementations.** Every screen talks to a typed `ApiClient`. With
`EXPO_PUBLIC_API_URL` set it is the real API over HTTP; without it, an in-memory mock with demo data for both
cities, whose holds expire and whose orders move through their states by the clock. Two reasons. Screens for
features the backend does not have yet (orders, tracking, the delivery code) could be built and looked at now, to a
written contract. And the laptop's network blocks the staging site, so the mock was the only way to run the app
there at all.

**What the mock promises, the backend must keep.** The account endpoints were written to the same contract the
mock used, and the app's HTTP client reads the backend's real shapes for everything that exists: accounts, cities,
hubs, serviceability, availability, checkout holds, produce items, farms and listings.

**The session is the backend's, kept properly.** Tokens live in the phone's secure store (Android Keystore through
`expo-secure-store`). The access token is renewed a minute before it runs out and once on a refusal, with one
renewal shared by every request in flight: the backend ends every session if a spent refresh token is presented
twice, so two renewals at once would sign the user out. On the web build the session is in `localStorage`, which
is said plainly in the code as a demo-only compromise.

**Looks taken from the genre, not from anyone.** Material Design 3, an original logo and icon set, one open-licence
typeface and one open-licence icon font. A location header, category chips, a deals strip and a floating cart bar
are common to shopping apps; no logo, artwork, name or screen of another company is used. `mobile/ASSETS.md` lists
every asset and its licence.

**No photos shipped.** The HLD wants real photographs from farmers and from the hub's quality check. Until those
exist, a product shows a tinted tile with a drawing; an `image_url` from the API replaces it.

## What was checked, and by whom

The app was built by a second agent working to a written brief; its report was not taken on trust.

- Type-check and web export were run again afterwards: both clean. Every test run on AWS now type-checks the app.
- In a browser at phone width, in mock mode, the following were walked through by hand a second time: sign-in with
  a code, choosing a delivery area, the shop with rescue deals, cart and bill, the hold with its countdown,
  payment, order tracking with the delivery code, and the farmer's home.
- The source was searched for keys and secrets: none.
- The session code was read: storage, renewal and sign-out behave as described above.

## What it leaves open

- **It has not run on a phone.** Fonts, safe areas, the keyboard, secure storage, the location prompt and
  pull-to-refresh are unseen on Android.
- **It has not talked to the real staging API**, only to a stand-in written from the backend's source.
- **Mocked, because the backend lacks them:** customer orders, order states after Packed, the delivery code,
  pooling, the agent's side, and a batch's grade, dates, markdown, farm and photo.
- **Staging will look bare** through this app today: produce has no stock until a farm lot is received and put
  away, and availability does not yet carry the batch details.
- **No map.** Location is the phone's GPS or a list of areas; the Google Maps pin-drop plugs in behind
  `LocationPicker`.
- **No release build.** An APK needs a build service or a machine with the Android SDK.

## Sources

- The project's HLD, section 15 (Expo, one app with screens per role) and section 16 (GPS rules).
- `mobile/ASSETS.md` for the licences: SIL Open Font License 1.1 (Plus Jakarta Sans), Apache License 2.0 (Material
  Design Icons), MIT (React Native Paper, Expo, React Native).
- Seen ourselves: everything under "What was checked".
