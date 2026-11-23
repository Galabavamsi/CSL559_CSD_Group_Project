# Bhilai gets hubs, the hub gets an intake screen, and the app meets a real phone

*23 November 2026. The two things that blocked a live demo from Bhilai are built, and the app's first run on a
phone found a fault no browser could show.*

## Context

The handbook written earlier in the day listed what a live demo in Bhilai lacked: the city had no hub on the real
backend and nothing could open one, and the hub's intake step was a command line. The phone app had only ever run
as a web build in a browser.

## What was built

| Piece | What it does |
| --- | --- |
| `POST /v1/admin/stores` | Opens a hub at a site: the hub, its 18 bins, its delivery zone and its four demo logins, in one transaction |
| `DEMO_HUBS` | Opens Bhilai's first three hubs in the demo data, once: at seeding, or at the next start of a copy seeded before |
| Network map | A city chooser, and "Open a hub here" beside each suggested site |
| `GET /v1/stores/{id}/lots-on-dock` | Lots weighed at a hub whose packs are not all put away, so an interrupted receiver can carry on |
| `web/intake.html` | The receiver's screen: lots on their way, weigh and grade, then one bin at a time |
| `mobile/src/components/KeyboardSpace.tsx` | Keeps the field being typed in above the keyboard on Android |

## Decisions, and why

**Opening a hub is one transaction, zones included.** A hub with no zone serves nobody, and a hub with a zone but no
bins cannot take a lot. So the hub, its bins and the recalculated zones are written together, and a refused request
(outside any city, on top of another hub, a name already used) changes nothing. Every zone is recalculated and not
only the new one, because the new hub takes over the cells it is nearest to.

**A hub must be inside a city.** The site has to lie within the built-up radius of the city it is opened in. Raipur,
30 km east of Bhilai's centre, is refused with the distance in the answer.

**Bhilai's hubs are demo data behind a setting, like the produce.** The tests count two hubs and stay as they were.
A hosted copy seeded before the setting existed gets the hubs at its next start, which is how staging will get them
without anyone touching its database by hand.

**Three hubs at 3 km leave Risali out on purpose.** Risali is 3.4 km from the Civic Centre hub. Customers there
are turned away, the map shows the red cells, and the suggested site sits among them with a button to open it.
That is the network-planning story told with the city the demo is in.

**The recorded demo moved to Bhilai.** Bhilai's hubs start empty and hold only what farms bring. The customer's
shop there lists the farmer's tomatoes and nothing else, where Bangalore's still lists the dark store's soap and
rice.

**The intake screen does one thing at a time.** It is the picker's screen turned around: one lot, then one portion,
then one bin, with buttons for a thumb. It says what will be packed before it is recorded (38 kg, 76 packs of
500 g), but the server decides. Every write carries an idempotency key, so a tap repeated on a bad connection is
done once.

## What the phone showed

The app ran in Expo Go on a Samsung Galaxy M34 (Android 16), on its built-in demo data, driven over USB with adb.
Sign-in, choosing an area, the shop, the cart, the hold with its countdown, checkout, payment, the order with its
door-step code, and the farmer's home all worked and looked right in the phone's dark theme.

**One fault: the keyboard covered the field being typed in.** On the sign-in screen the email field sat behind the
keyboard. The screens asked for keyboard handling on iOS only, on the belief that Android shrinks the window by
itself. It no longer does: Expo's Android apps are edge-to-edge, the window keeps its size, and Android 16 does not
let an app opt out. A browser has no on-screen keyboard, so the web build never showed it.

The fix took three tries on the phone, each of which a guess from the documentation would have got wrong:

1. Padding the form by the keyboard's height on Android too. The field moved up, but only its top edge showed.
2. Scrolling the field in use into view when the keyboard has opened. Still half hidden.
3. Adding the height of the system navigation bar. The keyboard's height comes without the bar under it, which an
   edge-to-edge app draws behind. With that, the field sits fully above the keyboard, on sign-in and at checkout.

## Mistakes made while testing on the phone

- **Typing with no field in focus.** A tap on a field's floated label does not focus the field, and keys typed
  with no field in focus are read by Expo Go as developer shortcuts, which closed the app. The helper now taps the
  field itself.
- **A tap that landed on the home screen.** After the app closed, one tap went to the phone's home screen. Nothing
  was changed there, but it should not have been possible: the helper now refuses to tap, type or press a key
  unless the app is in front.
- **A screen that never sits still cannot be read.** Android's UI dump waits for the screen to be idle, and the
  checkout's countdown never is. Positions were taken from a screenshot there.

## What was checked

- 23 new tests (21 for opening a hub, 2 for lots on the dock); the whole suite on the dev server and on AWS.
- The intake screen and the map's city view, in a real browser on the dev server, as part of the recorded run: one
  lot of tomatoes from a farm near Bhilai to a packed order, with no failed stage.
- "Open a hub here", pressed in a real browser on the site among Risali's turned-away customers: "BH-04 Risali"
  opened with 228 cells, an address in Risali that had been refused was served from 0.7 km, and the list of
  suggested sites moved on to the next gap.
- The app on the phone, as above.

## What it leaves open

- **The phone against the real backend.** The phone ran demo data. Staging has to be on this version first.
- **Registering a farm on the phone.** It needs the location permission, which is the owner's to grant.
- **Staging does not have Bhilai's hubs yet.** They arrive with the next deploy.
- **A hub's logins are demo logins.** Opening a hub creates four accounts with the environment's shared staff
  password. Real staff accounts are still to come.
- **The intake screen packs everything into the smallest unit.** The API can split a lot across pack sizes; the
  screen does not offer it.

## Sources

- Expo, "Keyboard handling" (Android apps are edge-to-edge and the window no longer resizes for the keyboard; do
  not combine panning with padding): https://docs.expo.dev/guides/keyboard-handling/
- Expo, app config reference (`softwareKeyboardLayoutMode`; Android 16 requires edge-to-edge):
  https://docs.expo.dev/versions/v54.0.0/config/app/
- React Native 0.86 release notes (edge-to-edge on Android and `KeyboardAvoidingView`):
  https://reactnative.dev/blog/2026/06/11/react-native-0.86
- Seen ourselves: every step on the phone, from screenshots taken over adb; the three tries at the keyboard fix;
  the distances, from the tests.
