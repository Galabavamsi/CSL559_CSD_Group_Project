# Staging on AWS

*23 November 2026. The app runs on AWS for the first time, at the staging address, and survives a database password
change and a database failover.*

## Context

Until now the prototype ran on one campus server. The target is a production-style set-up on AWS: private network,
managed database with a standby, HTTPS, a firewall, and deployments that can be repeated and rolled back. The
templates are in `infra/`; how to use them is in `infra/README.md`.

## What was built

| Layer | Choice |
| --- | --- |
| Network | One VPC over two availability zones. Public subnets hold only the load balancer and a NAT gateway; the containers are in private subnets; the database is in subnets with no internet route at all |
| Database | RDS PostgreSQL 16.15, `db.t4g.medium`, with a standby in the second zone, encrypted, 7 days of backups. PostGIS is created by the app at first start |
| App | One container on ECS Fargate (0.5 vCPU, 1 GB), behind an Application Load Balancer with TLS 1.2 and 1.3 only |
| Firewall | AWS WAF on the load balancer: a rate limit per address, AWS's lists of bad addresses, its common-attack rules and its known-bad-inputs rules |
| Build | CodeBuild clones one chosen commit of the public repository, builds the image and pushes it to ECR, tagged with the commit |
| Deploy | `infra/deploy.ps1` builds a commit and updates the app stack. ECS starts the new version, waits until it is healthy, then stops the old one, and rolls back a version that never gets healthy |

All of it is four CloudFormation templates deployed with the AWS CLI.

## Decisions, and why

**CloudFormation with the plain CLI, not CDK or Terraform.** The development laptop blocks some unsigned programs,
and the other stacks already in this AWS account are CloudFormation. Nothing extra has to be installed.

**Nothing in GitHub can start a build or a deployment.** The repository is public. The usual set-up, where a push
to `main` deploys, makes every person who can push a person who can deploy. Here someone signed in to AWS chooses a
commit and starts the build; the build's role can push to one image registry and do nothing else. Image tags are
commit ids and cannot be overwritten, so going back to an older version is deploying its commit again.

**The database password is read when a connection is opened, not handed over once at start.** This is the decision
that would have hurt most if missed. RDS creates the master password itself and keeps it in Secrets Manager, which
is why no template or person ever holds it. But it also changes that password every seven days by default; on our
secret the next change was scheduled for 30 November, three or four days before the demo. ECS can pass a secret to a
container as an environment variable, but only when the container starts. A container started on the 23rd would
have kept working on connections it already had, and failed on every new one from the 30th.

So the container is given the secret's address, not its contents. Each new database connection asks for the login
at that moment; the answer is remembered for five minutes; and if the database refuses the password, the login is
fetched again once and the connection retried (`app/db.py`, `_log_in_with`). Tests run this against a real
PostgreSQL that refuses a wrong password: refused then fetched again succeeds; wrong twice is an error, not a loop;
a failure that is not about the password is not retried.

**The server believes `X-Forwarded-For` only from the VPC.** The app limits requests per client address. Behind a
load balancer every request arrives from the load balancer, and the caller's address is in the `X-Forwarded-For`
header, to which the load balancer appends the real address on the right. A caller can put anything on the left.
We tried both settings on the server we run (uvicorn 0.54.0), sending the header `1.2.3.4, 203.0.113.9`:

| Trusted proxies | Address the server used |
| --- | --- |
| `*` (everyone) | `1.2.3.4`, the value the caller invented |
| the VPC's range | `203.0.113.9`, the one a load balancer would have appended |

Trusting everyone would let a caller get a fresh rate-limit allowance with every request by changing one header.

**A password for the staff screens of a hosted site.** The demo pages log in with the built-in password `demo`,
which is in the public source. Each environment now gets a generated staff password in Secrets Manager, and the
pages ask for it once when the built-in one is refused. It is a stopgap until real accounts replace the demo logins.

**One copy of the API for now.** The timed jobs and the live event feed run inside the API process. Two copies would
run the jobs twice, and a browser would see only the events relayed by the copy it is connected to. Running more
copies needs those two moved out first; the load balancer, the standby database and the rollback are already there.

**One NAT gateway.** A second, in the other zone, would keep outbound traffic working if a zone failed. The account
allows five Elastic IP addresses in the region and other projects use three.

**The firewall's body-size rule only counts.** AWS's common rule set blocks any request body over 8 KB. A goods
receipt or a stock count with many lines is larger, so that one rule is set to count, not block.

**The base image comes from Amazon's mirror of Docker Hub.** Builds on AWS leave from addresses shared with other
customers, and Docker Hub limits anonymous downloads per address, so a build can fail because of someone else's.

## What was checked on the running site

From a machine on the public internet, outside the app's network (`infra/smoke.sh`):

- HTTPS with a verified certificate, TLS 1.3 and HTTP/2; TLS 1.1 refused; plain HTTP redirected (301).
- The API answers, including both PostGIS queries; a checkout hold can be made and released.
- The built-in staff password is refused (401); a staff endpoint without a token is refused (401).
- The firewall blocks a request with a script tag in its query and one with no user agent (403 each).
- The load balancer passes a WebSocket upgrade (101).
- 40 calls at once all succeed.
- The app's own log shows the caller's public address on its requests, and no VPC address.

Then two tests on purpose:

1. **Password change.** We made RDS change the master password (74 seconds). 80 parallel calls afterwards all
   succeeded. That alone proves little, since fast calls can be served by connections opened before the change.
2. **Failover.** So we forced the database over to its standby, which closes every connection. RDS reported the
   failover started at 20:20:34 UTC and completed at 20:21:08. A probe calling a database-backed endpoint about
   once a second saw two failed calls, the first at 20:20:35 and the last at 20:20:44, and success again from
   20:20:49. The container was not restarted. Every connection after that was new and logged in with the changed
   password. The app's log shows two connection errors for the whole episode.

What this does not show: the "refused, then fetched again" path did not run on staging, because by the time new
connections were needed the remembered login was more than five minutes old and was fetched fresh. That path is
covered by the tests only.

## Problems on the way

- **The laptop could not reach the site.** The network it was on answered plain HTTP with a "blocked in accordance
  with company policy" page and reset HTTPS for the new domain. The site was fine; the checks were run from a
  server in AWS. Worth knowing before a demo on such a network: a new domain may be blocked there.
- **Windows PowerShell 5.1 could not call the site either**, for a different reason: it offers TLS 1.0 unless told
  otherwise, and the load balancer accepts 1.2 and 1.3 only. `infra/deploy.ps1` now asks for TLS 1.2.
- **`aws cloudformation deploy` keeps old parameter values.** Changing a default in a template does nothing for an
  existing stack unless the new value is passed with `--parameter-overrides`.

## What it costs

On-demand prices for Mumbai from the AWS Price List API on 23 November 2026, in US dollars:

| Item | Price | Per day |
| --- | --- | --- |
| Database, `db.t4g.medium` with standby | 0.167 per hour | 4.01 |
| Database storage, 50 GB gp3 with standby | 0.262 per GB-month | 0.44 |
| NAT gateway | 0.056 per hour, plus 0.056 per GB | 1.34 |
| Load balancer | 0.0239 per hour, plus 0.008 per capacity unit-hour | 0.57 |
| Container, 0.5 vCPU and 1 GB | 0.04256 per vCPU-hour, 0.004655 per GB-hour | 0.62 |
| Three public IPv4 addresses | 0.005 per hour each | 0.36 |
| Firewall: one web ACL and four rules | 5 and 1 per month, plus 0.60 per million requests | 0.30 |
| Three secrets | 0.40 per month each | 0.04 |
| **Staging, about** | | **7.70** |
| Dev server, `m7i.xlarge` (separate from staging) | 0.2121 per hour | 5.21 |

About 13 dollars a day with the dev server, before data transfer, logs and build minutes, which are small at this
size. The database with its standby is half of staging's cost.

## Sources

- AWS, "Password management with Amazon RDS and AWS Secrets Manager" (the seven-day default):
  https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html
- AWS, "Pass Secrets Manager secrets through Amazon ECS environment variables":
  https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html
- AWS, "HTTP headers and Application Load Balancers" (`X-Forwarded-For` is appended to):
  https://docs.aws.amazon.com/elasticloadbalancing/latest/application/x-forwarded-headers.html
- MDN, `X-Forwarded-For` (which end of the list can be trusted):
  https://developer.mozilla.org/docs/Web/HTTP/Headers/X-Forwarded-For
- AWS WAF, "Baseline rule groups" (`SizeRestrictions_BODY`, 8 KB):
  https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-baseline.html
- AWS, "How the Amazon ECS deployment circuit breaker detects failures":
  https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html
- AWS re:Post knowledge center, Docker Hub pull limits in CodeBuild:
  https://repost.aws/knowledge-center/codebuild-docker-pull-image-error
- Seen or measured ourselves: the rotation schedule on our own secret; uvicorn's choice of client address; every
  check and both tests above; the prices, read from the AWS Price List API.
