# Recording the demo, and what the recording found

*23 November 2026. A script drives the real backend through the phone app and the hub's pages and records it. Its
pictures and video feed a handbook. Writing the handbook's demo page found that Bhilai has no hub.*

## Context

Two things were asked for: a PDF that explains what is built, how the micro-warehouse works, what was measured and
how to demo it; and a video of the farmer, the customer, the hub and the delivery agent at work. Screenshots taken
by hand go stale the day after they are taken, so both are made by a script that can be run again.

## What was built

| Piece | What it does |
| --- | --- |
| `scripts/record_demo.sh` | On the dev server: an empty database, the API with sales history, the phone app's two web builds, then the recorder and the composer |
| `scripts/record_demo.py` | Playwright drives one lot of tomatoes through the farmer's app, the hub's intake, the customer's app and the picker's page, saving a screenshot at each step and a video of each part, and noting what to caption when |
| `scripts/compose_demo.py` | ffmpeg sets each clip on a page beside its title, a line saying what is real in it, and the caption for that moment, and joins the parts |
| `scripts/hub_intake.py` | Weighs, grades and puts away one lot from the command line: the hub's intake step has no screen yet |
| `docs/handbook/` | The handbook's pages as HTML, its pictures, the video, and `build.ps1`, which prints the PDF |

## Decisions, and why

**The app is recorded from its web build, at phone size.** The same code runs on a phone, and a browser can be
driven and recorded on a server with no screen. The cost is real and is stated in the handbook: nothing here has
been seen on a phone.

**The recording runs on the dev server, not on staging.** It needs an empty database every time and it reads the
sign-in code from the API's log, which only the development email backend writes. On staging the code goes by
email and never reaches a log.

**The browser runs with web security off.** The web build and the API are on different ports there, and the API
sends no cross-origin headers. A phone app has no such rule, so nothing was added to the API for the recording.

**Every part of the video says what is real in it.** Six parts are the real backend. The seventh is the app's
built-in demo data and says so on screen for its whole length. Delivery is not built and is not shown, and the
opening card says that too.

**A stage that fails leaves a picture and lets the rest run.** The first runs stopped at the first fault, eight
minutes apart. After the change one run showed every fault.

## What went wrong on the way

- **Text that was on screen three times.** React Navigation keeps the screens it has left mounted, and the web
  build keeps them in the page, hidden. Playwright refuses to act when a locator matches more than one element, so
  "My listings" failed with three matches. The recorder now counts only what is visible.
- **"Bangalore" matched seven things.** A role lookup by name matches part of a name unless told otherwise, and
  every area is "…, Bangalore". Asking for the exact name fixed it.
- **"Pay" was not the button.** The checkout says "Pay before the clock runs out" above a button that says
  "Pay ₹48". The first text starting with "Pay" was the sentence, and clicking it does nothing. The button is now
  found by its rupee amount. A person would never have made this mistake; a script made it twice.
- **A character the laptop could not print.** A failed stage's dump of the screen included an icon-font character,
  and the AWS CLI on Windows stopped with an encoding error while printing it. The output is now reduced to plain
  ASCII on the server.

## What it found

**Bhilai has no hub on the real backend.** The city is there with its tier and radius, and the seed data's comment
says its hubs "come from hub placement". But nothing can open a hub: the network map only suggests sites. A lot
listed from a farm in Bhilai is refused, because no hub is within 60 km, and a Bhilai address is not serviceable.
The phone app's demo data has Bhilai hubs, which is why this went unnoticed. The demo is in Bhilai and a farm's
location is the phone's own GPS fix, so the farmer's half of a live demo cannot be done from there until this is
built. It is first in the handbook's list of what is left.

**The hub's demo data is still a dark store's.** The customer's shop on the real backend lists bath soap and
basmati rice beside the farmer's tomatoes. The recording shows the Vegetables tab and the handbook says why.

## What was checked

- The whole run, five times, the last one with no failed stage: 7 clips, 33 screenshots, a video of 3 min 29 s.
- Stills taken from the finished video at 14 points were looked at: titles, the "what is real" line and the
  captions are where they should be and none is cut off.
- Every page of the PDF was read after it was printed.
- `scripts/hub_intake.py` took in a second lot on the same server (see the handbook's metrics page for the run).

## What it leaves open

- The app on a real phone, against staging. Still not done.
- The video has no sound.
- The recorder knows the screens' words. A change of wording in the app breaks it, and it says where.

## Sources

- Playwright, "Locators" (locators are strict; matching only visible elements):
  https://playwright.dev/python/docs/locators
- React Navigation, "Navigation lifecycle" (a screen is not unmounted when another is pushed over it):
  https://reactnavigation.org/docs/navigation-lifecycle/
- Chrome for Developers, "Add content to the margins of web pages when printed using CSS" (page margin boxes, used
  for the PDF's footer and page numbers): https://developer.chrome.com/blog/print-margins
- Seen ourselves: every fault above, from the recorder's own output and its failure pictures; the Bhilai finding,
  from the seed data, the endpoints and a call to the running API.
