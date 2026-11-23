# Accounts: signing in with a code sent by email

*23 November 2026. Customers, farmers and delivery agents get accounts. There are no passwords.*

## Context

The prototype had one kind of login: hub staff with a username and password. The customer endpoints were open to
anyone. The phone app needs to know who is ordering, who is listing produce and who is delivering.

SMS codes were the first idea and were ruled out for now: sending SMS to Indian numbers needs a registered sender
and registered message templates, which does not fit the time before the demo. Email works today, through Amazon
SES on the project's own domain.

## Decision

An app user signs in by typing their email address and then a six-digit code sent to it. The first sign-in of an
address creates its account. The code is in `app/modules/accounts/`.

| Rule | Value | Where it comes from |
| --- | --- | --- |
| A code is random | `secrets`, six digits | OWASP: a cryptographically secure generator |
| It works once | spent by one conditional `UPDATE`, so two uses at once cannot both win | OWASP: single use, invalidated after success |
| It expires | 10 minutes | OWASP: a short time to live |
| Wrong tries are limited | 5 per code, counted before the code is compared | OWASP: strict attempt limits |
| It is not stored as sent | only an HMAC of it, keyed with a server secret | OWASP: not in plain text; and see below |
| Asking again | once a minute, five times an hour per address; a new code replaces the old | OWASP: per-account rate limiting, replace on resend |
| The answer gives nothing away | the same words whether or not the address has an account, and the email is sent after the answer | OWASP: same message, similar time |

**Why a keyed hash.** OWASP notes that a one-time code has so few possible values that anyone holding the database
can reverse a plain hash by trying them all. Six digits is a million tries. Keying the hash with a secret that is
not in the database (HMAC) means the stored value is useless without that secret.

**Why six digits when OWASP suggests eight "where usability allows".** A person types this on a phone, usually from
a notification. With five tries per code and five codes an hour, an attacker gets 25 guesses an hour at a
one-in-a-million target. We kept six and kept the limits strict.

**Delivery agents do not register themselves.** A customer or a farmer registers by signing in. An agent's account
is created by the platform team (`POST /v1/admin/users`), because an agent sees customers' addresses. An unknown
address that asks to be an agent gets the same answer as everyone else and is sent nothing; the row written for it
is already spent, so there is no code to guess.

**Sessions.** A sign-in returns an access token that lasts 60 minutes and a refresh token that lasts 30 days. The
app exchanges the refresh token for a new pair before the access token runs out. A refresh token works once. If one
that was already exchanged is presented again, a copy exists somewhere, and every session of that user is ended.
Only a hash of a refresh token is stored.

## A hole this closed

Adding a second kind of token exposed a weakness in the first. Many staff endpoints asked only for "any logged-in
staff", and a staff member with no store counts as city-wide. A customer's token is a valid token with no store.
Without a check it would have opened the dashboards, the forecasts and the live event feed of every hub. Staff
endpoints and the live feed now refuse a token whose role is not a staff role, and the app-user endpoints refuse a
staff token. Three tests hold that line.

## What was checked

- 32 tests, on a real PostgreSQL, including: two uses of the right code at the same moment sign in once; the sixth
  try fails even with the right code; a code for one address is no good for another; a spent refresh token ends
  every session; an email that cannot be sent does not fail the request and puts no code in the log.
- On staging, from outside: a code asked for Amazon SES's simulator address was accepted, SES recorded one send,
  and the app's log held no send error and no code. Asking again at once was refused with the wait; a wrong code,
  a bad address, an unknown refresh token and a made-up access token were each refused as designed.
- Not checked on staging: a complete sign-in, which needs a real inbox to read the code from.

## What it costs or leaves open

- Email is a weaker second channel than a phone. Whoever reads the inbox can sign in.
- On a laptop the email backend writes each message, code included, to the log. That is for development only; in
  AWS the backend is SES and the log never holds a code.
- A phone number is collected in the profile but not verified.
- Old sessions are not listed anywhere for the user to end one by one.
- The per-address limits are in the database; the per-caller limit is still the in-process rate limiter and the
  firewall in front.

## Sources

- OWASP Cheat Sheet Series, "Multifactor Authentication" (one-time codes: short life, single use, attempt limits,
  no plain-text storage, the small keyspace, replace on resend, eight digits where usable):
  https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
- OWASP Cheat Sheet Series, "Forgot Password" (same message and similar time whether or not the account exists,
  per-account rate limiting): https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html
- AWS, "Using the mailbox simulator" (test addresses that do not affect bounce and complaint rates):
  https://docs.aws.amazon.com/ses/latest/dg/send-email-simulator.html
- AWS, "Actions, resources, and condition keys for Amazon SES" (`ses:FromAddress`):
  https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonses.html
- Still to cite: the SMS registration rules for India.
