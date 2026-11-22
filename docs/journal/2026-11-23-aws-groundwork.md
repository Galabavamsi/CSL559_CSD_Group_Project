# AWS groundwork

*23 November 2026. What was set up before any application code ran on AWS, and why in that order.*

## Context

The app moves from a campus lab server to AWS, for a demo in early December. The AWS account is shared with other,
unrelated projects.

## Decisions

**Work as an IAM user, not as root.** The command line was first signed in as the account's root user. Root cannot
be restricted, so a mistaken command has no ceiling. We switched to an existing administrator IAM user and added MFA
to it. IAM users cost nothing. Billing pages stay "access denied" for every IAM user, administrator or not, until
root turns on *IAM user and role access to Billing information* once in the account settings.

**No IAM Identity Center for now.** It is the recommended way to sign in, but using it for account access means
turning the account into an AWS Organization. That is an account-wide change, and other projects live in this
account, so it was left alone.

**One tag on everything.** Every resource carries `Project=farm2home`. A monthly budget filtered on that tag sends
email at 50% and 80% of actual spend and at 100% of forecast, so this project's cost is visible apart from the
others'.

**A delegated subdomain.** The domain's DNS stays at its current provider. One subdomain is handed to Route 53 with
four NS records, so certificates, email records and service addresses can be created without a manual DNS change
each time.

**Certificates in two regions.** A certificate for the subdomain and its wildcard was requested in Mumbai (for the
load balancer) and in us-east-1, because CloudFront only takes certificates from us-east-1. Both validate through
one DNS record.

**Email one-time codes, not SMS.** Login codes go by email through Amazon SES, with DKIM, a custom MAIL FROM domain
and a DMARC record on the subdomain. SMS to Indian numbers needs sender and template registration first, which does
not fit the time available. The delivery code is shown inside the customer's app and typed by the delivery agent,
so it needs no SMS either.

**A dev server instead of the laptop.** The development laptop cannot run the test suite (a security policy blocks
a compiled library) and has no Docker. A 4 vCPU server in Mumbai runs PostgreSQL with PostGIS, Redis and the tests.
It has no inbound network rule at all and no SSH key; commands reach it through AWS Systems Manager.

## What it cost or leaves open

- The dev server is about 0.20 USD an hour while it runs.
- The hosted zone is 0.50 USD a month.
- The repository is public and owned by another account, so the deploy pipeline must only ever trust the `main`
  branch and release tags of this repository, never any branch.
- Teammates, if they need access, get their own IAM users limited to resources with this project's tag.

## Sources

- AWS, "Root user best practices": https://docs.aws.amazon.com/IAM/latest/UserGuide/root-user-best-practices.html
- AWS, "Requirements for using SSL/TLS certificates with CloudFront" (us-east-1):
  https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html
- Seen in our own account, not taken from a document: an administrator IAM user got "Access denied" on the cost
  pages until root activated IAM access to billing, and could read cost data afterwards.
- Still to cite: the SMS registration rules for India, and the Systems Manager documentation.
