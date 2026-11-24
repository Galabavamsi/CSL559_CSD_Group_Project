# A sign-in box for the hub pages, and a repository ready to hand over

*24 November 2026, afternoon. A second person could not use the hub desk while the owner was signed in. The cause
was not a limit on sessions but the way the pages asked for the password. Then the repository was made ready for
someone new: an in-depth handover, a front page that describes what the project is now, and the group project's
papers moved aside.*

## Context

The owner showed the hub desk to a colleague on staging and reported that the other person "cannot access it in
parallel". The owner was about to hand the project over and asked for "a clean, well documented repo".

## What was built

| Piece | What it does |
| --- | --- |
| `web/staff-login.js` | Every hub page's login. It now draws its own sign-in box instead of using `window.prompt` |
| `docs/HANDOVER.md` | Rewritten in depth: eighteen sections, from the project in one page to a glossary |
| `README.md` | Rewritten as the front page: every link to see it, what it does, how to run it, where the documents are |
| `docs/README.md` | A guide to the documents folder: what each document is for, and which are kept current |
| `docs/history/` | The group project's plan, member guides, report and old single-server deploy guide, moved out of the way, with a page saying what they were |
| `docs/ARCHITECTURE.md`, `CONTRIBUTING.md`, `infra/README.md`, `mobile/README.md`, `docs/DEMO_SCRIPT.md` | Checked against the code and brought up to date |

## What went wrong, and how it was found

**The second person's browser was sending a wrong password, again and again.** Nothing in the system limits
sessions: staff tokens are independent and the owner's own logins went through. Staging's request log showed about
40 refused logins from 12:11 IST, one or two at every refresh of a page. The firewall's sampled blocks showed only
internet scanners. The pages asked for the password with `window.prompt`, and two things followed from it:

- A mistyped password was saved and sent again at every refresh, and the page asked again only after a reload.
- Browsers opened from inside other apps (a link tapped in WhatsApp or Gmail) often suppress `prompt`, so the
  question may never have appeared. A password copied out of a chat can also carry a trailing space.

The page now draws the box itself. A refused password is forgotten and asked for again at once, with a message;
spaces around a pasted password are trimmed; Cancel stops the asking until a reload, instead of the box coming back
at every refresh. It was checked on the development server with three browsers at once against a fresh API whose
password is not the built-in one: eight checks, all passed. It was not checked inside a real in-app browser.

**A promise in the chat was wrong.** Earlier the same day the owner was told the staff password could be replaced
in AWS and staging restarted. Writing the handover showed otherwise: the password is hashed into each staff account
when the accounts are created, so a new secret alone would leave every staff login on the old password. The
handover now says that a change needs a migration or an admin call that does not exist yet.

**The AWS sign-in on the laptop expired** in the middle of this work, so the test run and the deploy could not
start. The two pull requests merged in this stretch had been checked before it expired (800 tests on AWS for the
documents and the renamed titles; the sign-in script by Node's syntax check and the three-browser run).

## Decisions

- **The group project's papers are kept, not deleted.** They are the record of four people's work and explain the
  task numbers ("task 1.6") still found in comments. They moved to `docs/history/` so that nobody mistakes them for
  current instructions.
- **The README is a front page, not a manual.** It says what the project is, where to see it and how to start, and
  points to the handover for everything else. The long table of services moved to `docs/ARCHITECTURE.md`, next to
  the code it describes.

## Sources

- MDN Web Docs, `Window: prompt() method` (browsers may ignore the call, for example where dialogs are suppressed):
  https://developer.mozilla.org/en-US/docs/Web/API/Window/prompt
