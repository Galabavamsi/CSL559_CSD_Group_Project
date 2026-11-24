# An app that installs, and a demo one person can run

*24 November 2026. The owner has to show the work to a professor, from a phone. Two things stood in the way. The
app ran only inside Expo Go, loaded from a laptop over a cable. And between a customer's payment and an agent's
trip, someone had to stand at the hub and pick and pack. Both are dealt with; this entry says how and what it
cost.*

## Context

Delivery went onto staging the same morning (see [An order reaches a door](2026-11-24-an-order-reaches-a-door.md)).
The whole flow existed, but showing it needed a farmer, a receiver, a picker, a customer and an agent, a laptop
for the hub's screens, and a cable. The request was: "make the app download in phone, and make it demoable".

## What was built

| Piece | What it does |
| --- | --- |
| `scripts/build_apk.sh` | Builds an Android APK from `mobile/` with the API's address built in |
| `android.package` in `app.json` | The app's Android name, `com.galabavamsi.farm2home` |
| `app/demo_hub.py`, `DEMO_AUTOPACK` | An order no picker claims within 45 seconds is picked and packed by the app, as a picker would |
| Staging's settings | Demo hub on; a lone packed order leaves after half a minute; 15 sign-in codes an hour per address |
| `docs/DEMO_ON_A_PHONE.md` | A run sheet: what to install, tap and say, and what is not built |

## Decisions, and why

`docs/DESIGN.md` sections 4.11 and 7 hold the reasoning. In short:

**Built on our own server, not by Expo's build service.** Expo's service needs an account and uploads the project
to its cloud for every build. The dev server was there. It needed Java 17 and the Android SDK and NDK, about
2.6 GB, and accepting Google's licence for the SDK; the owner was asked first and said yes. The first build took
eleven minutes.

**Signed with the debug key.** Expo's generated Android project signs a release with the debug keystore until a
real one is configured, and its guide says plainly that a store release needs your own. For installing by hand on
a few phones that is enough, and it avoids creating a signing key that would then have to be kept safe for the
life of the app.

**The demo hub picks; it does not mark the order packed.** Packing is where a sale is committed: stock leaves the
shelf, the hold ends, and the bill follows the batches picked. So the demo hub claims the order with the picker's
own guarded update, scans each line against its barcode, and packs into a free crate slot. One of its tests
expires a batch after payment: the demo hub does what the picker's screen tells a person to do, "not on shelf",
and the line moves to a fresh batch.

**The settings are on staging only.** Demo farms, the demo hub, a half-minute wait and open sign-up for agents
are each off unless turned on, and each is named for what it is.

## What went wrong

- **A setting nearly went out unreviewed.** The staging settings live in the CloudFormation template, which the
  deploy script reads from the working folder. It was edited for this change while the deploy of the previous one
  was still in its test stage. The edit was taken back out before the deploy reached the template, and put back
  after. A deploy should read the template of the commit it deploys, not whatever is on disk. `infra/deploy.ps1`
  now takes the template out of that commit with `git show`; the change that carries this entry makes it so.
- **A download link that would not last.** The first plan for getting the APK onto a phone was a week-long link
  to the private bucket. The laptop's AWS sign-in is a session, so a link signed with it dies with the session,
  within hours, whatever lifetime is asked for. The owner's phone was plugged in by then and the app was installed
  over the cable. A link that lasts needs a public home for the file, which is the owner's decision.

## What was checked

- The APK: built, 36.8 MB, `arm64-v8a`, version 1.0.0; its bundle contains the staging address and not the local
  one; all 40 photographs are in it. Installed on a Samsung Galaxy M34 and started: the sign-in screen came up
  with no laptop behind it.
- The demo hub: seven tests, one of them from paid to delivered with nobody at the hub. The whole suite, 800,
  passes on AWS.
- On staging after the deploy: one order paid at a hub's desk, with nobody at the hub, read "fulfilled" 50 seconds
  later, which is what packing does. The smoke test passes.

## What it leaves open

- Signing in and ordering from the installed app had not been done when this was written: it needs the owner's
  emailed code.
- The campus Wi-Fi blocks the staging address. The demo needs mobile data until the app can reach the API by an
  address the filter knows.
- The deploy script's new step was tried by hand (the commit fetched, its template written and validated by
  CloudFormation) but has not yet run inside a deploy.
- One phone playing customer and agent has to sign out and in, and each time is one more emailed code.

## Sources

- Expo, "Create a release build locally" (the Android project is generated by `npx expo prebuild`; a release is
  signed with the debug keystore until an upload key is configured):
  https://docs.expo.dev/guides/local-app-production/
- Expo, "Build locally: Overview": https://docs.expo.dev/guides/local-app-overview/
