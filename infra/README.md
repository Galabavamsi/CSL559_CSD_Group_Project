# Running on AWS

Everything runs in one AWS account, in Mumbai (`ap-south-1`), from five CloudFormation templates deployed with the
AWS CLI and three scripts that test, deploy and smoke-test. Nothing here needs Node, CDK or Terraform. Every resource
is tagged `Project=farm2home`; the account holds other projects, which are not to be touched.

The commands are for PowerShell on Windows, from the repository's folder, with the AWS CLI signed in and the GitHub
CLI (`gh`) signed in. The laptop's AWS sign-in is a session that ends after some hours: a script that stops with
"Your session has expired" has changed nothing, so sign in and run it again.

## What runs where

| Stack | Template | What it holds | How many |
| --- | --- | --- | --- |
| `farm2home-network` | `network.yml` | A VPC over two availability zones: public subnets (load balancer, NAT gateway), private subnets (the containers), isolated subnets (the database) | one |
| `farm2home-build` | `build.yml` | The image registry (`farm2home/api`, the newest 30 images kept) and the CodeBuild project `farm2home-build`, which builds one chosen commit | one |
| `farm2home-ci` | `ci.yml` | The CodeBuild project `farm2home-test`, which tests one commit against PostGIS in a container, and its own copy of the PostGIS image | one |
| `farm2home-data-<env>` | `data.yml` | PostgreSQL 16 on RDS (`db.t4g.medium`, 50 GB) with a standby in a second zone, seven days of backups, and its security groups | one per environment |
| `farm2home-app-<env>` | `app.yml` | The API on ECS Fargate (one container, 0.5 vCPU and 1 GB), the HTTPS load balancer, the web application firewall, the DNS name, the generated secrets and the app's settings | one per environment |

One environment exists: **staging**, at https://staging.farm2home.galabavamsi.com. The templates also allow `prod`
(at the domain itself); none has been made, and [`docs/DESIGN.md`](../docs/DESIGN.md) section 6 says why.

Outside the stacks, made by hand once: the Route 53 hosted zone and the certificates, the email identity in Amazon
SES, a monthly budget on the `Project=farm2home` tag, the dev server (below), the private artifacts bucket, and the
Amazon Location key for map tiles (`farm2home-map-tiles`), which nothing uses yet.

## Testing a commit

```powershell
infra\test.ps1 -Ref f2h/some-branch
```

`-Ref` is a branch, a tag or a full commit id. The script runs `infra/ci-test.sh` for that commit in CodeBuild:
PostgreSQL with PostGIS in a container, the migrations built from empty and compared with `app/models.py`, a syntax
check of the hub pages' scripts, a type-check of the phone app, and the whole test suite (800 tests). It takes about
five minutes, prints the result, and sets a commit status in GitHub through `gh`, so the commit's pull request shows
a check named "tests (AWS CodeBuild)". A commit that already passed is not run again unless you add `-Rerun`;
`-NoStatus` leaves GitHub alone. It exits 1 when the tests fail.

A test run is trusted with nothing but its own logs and its copy of the PostGIS image. It runs the code it is
testing, so it has no way to reach the app, its database, its registry or any secret.

**Runs started by a push are not switched on.** The AWS connector for GitHub has not been given access to this
repository, so `test.ps1` is run by hand. To switch it on, give the stack an authorised connection; every push then
starts a run, and CodeBuild reports the result on the commit itself:

```powershell
aws codeconnections create-connection --provider-type GitHub --connection-name farm2home-github
# then, once: AWS console > Developer Tools > Settings > Connections > farm2home-github > Update pending connection,
# and install the AWS connector on this repository only
aws cloudformation deploy --stack-name farm2home-ci --template-file infra/ci.yml --capabilities CAPABILITY_NAMED_IAM `
    --tags Project=farm2home --parameter-overrides ConnectionArn=<the connection's ARN>
```

## Deploying a version

```powershell
infra\deploy.ps1 -Env staging -Ref main
```

About fifteen minutes. The script:

1. Finds the commit `-Ref` names in the public repository.
2. Makes sure that commit's tests have passed on AWS, running `test.ps1` if they have not, and stops if they fail.
   `-SkipTests` is for an emergency and says so loudly.
3. Has CodeBuild build the commit's image, tagged with the first 12 characters of the commit, unless the registry
   already has it.
4. Takes `infra/app.yml` **from that commit** (`git show <commit>:infra/app.yml`), not from your working folder, and
   deploys it with the new image tag. An edit in progress in your folder cannot ship with another commit's code; to
   change staging's settings, commit the change to `app.yml` and deploy that commit.
5. ECS starts the new version, waits for the load balancer to find it healthy, then stops the old one. A version
   that never gets healthy is rolled back by itself.
6. Prints the address and calls `/health`. From a network that blocks the staging address (the owner's campus
   Wi-Fi and the development laptop's network both do) that last call fails; that line alone does not mean the
   deploy failed.

The app applies any new database migration when it starts, so a deploy is also how staging's tables change.

**Going back.** Deploy the earlier commit again: its image is still in the registry, and its own `app.yml` comes
with it, settings included.

**Why deploys start from AWS, not from a push to GitHub.** The repository is public. A push may one day start a test
run, which is trusted with nothing; it cannot start a build or a deployment. Someone signed in to AWS chooses a
commit and deploys it, and the image build can do one thing in the account: push an image to the registry.

## Checking a deploy

From a machine that can reach staging (the dev server can; the laptop on campus Wi-Fi cannot):

```bash
bash infra/smoke.sh https://staging.farm2home.galabavamsi.com
```

It needs no login and leaves nothing behind but one released hold. It checks `/health`, the redirect from HTTP to
HTTPS, the certificate and that TLS 1.1 is refused, the cities and three points (Bangalore, Bhilai, and one nobody serves),
the pages and `/docs`, that the built-in `demo` password is refused (`401`), that a staff call with no token is
refused (`401`), that the firewall blocks a script tag in a query and a request with no user agent (`403`), one
checkout hold made and released, the WebSocket upgrade (`101`), and a burst of 20 calls at once (all `200`). Each
line says what to expect.

## Logs, metrics and a shell

| What | Where |
| --- | --- |
| The API's output | CloudWatch Logs, `/farm2home/staging/api`, kept 30 days. One JSON line per request (method, route, status, milliseconds, `request_id`); warnings and errors from the timed jobs as plain lines |
| Test runs | `/farm2home/test` |
| Image builds | `/farm2home/build` |
| The database's own log | `/aws/rds/instance/farm2home-staging/postgresql`; slow queries in Performance Insights (seven days) |
| CPU and memory of the container | CloudWatch Container Insights, cluster `farm2home-staging` |
| What the firewall blocked | The WAF console, web ACL `farm2home-staging`: its metrics and sampled requests |
| Who called which staff endpoint | `GET /v1/audit`, as `admin` |
| The app's counters and timings | `GET /metrics`, in Prometheus' text format. Nothing on AWS scrapes it, and on staging it answers anyone because `METRICS_TOKEN` is not set: a known fault in [`docs/HANDOVER.md`](../docs/HANDOVER.md) |

```powershell
aws logs tail /farm2home/staging/api --follow                                # as it happens
aws logs tail /farm2home/staging/api --since 1h --filter-pattern ERROR       # what went wrong in the last hour
aws ecs describe-services --cluster farm2home-staging --services api --query "services[0].deployments"
```

Every answer carries an `X-Request-ID` header; search the log for that id to follow one request.

**A shell in the running container** (needs the Session Manager plugin for the AWS CLI):

```powershell
aws ecs list-tasks --cluster farm2home-staging --service-name api --query "taskArns[0]" --output text
aws ecs execute-command --cluster farm2home-staging --task <task id> --container api --interactive --command /bin/sh
```

## The staff password and other secrets

| Secret | Where | Who reads it |
| --- | --- | --- |
| Staff password | Secrets Manager, `farm2home/staging/staff-password`, generated by the app stack | The hub pages: every staff login on staging (`picker<n>`, `packer<n>`, `receiver<n>`, `manager<n>`, `ops`, `admin`) uses it. Its value is never written in this repository |
| Token signing secret | `farm2home/staging/jwt-secret`, generated by the app stack | The app (`JWT_SECRET`). It signs every token, keys the stored hashes of sign-in codes and derives the door codes: changing it ends every token in use (the phone app renews its own), voids codes waiting to be typed, and changes the door code of every order still out |
| Database login | Made and kept by RDS, which changes it every seven days | The app reads it whenever it opens a connection (`DB_SECRET_ARN`), so a change needs no restart |

The hub pages ask for the staff password in a sign-in box of their own the first time a login is refused, and the
browser remembers it. To read it:

```powershell
aws secretsmanager get-secret-value --secret-id farm2home/staging/staff-password --query SecretString --output text
```

## Staging's settings

The app's settings for an environment are the `Environment` list of the task definition in `infra/app.yml`. Staging
turns on the demo's stand-ins, each off by default in `app/config.py`:

| Setting | On staging | What it does |
| --- | --- | --- |
| `DEMO_PRODUCE` | `on` | The produce items and their units, for farmers to list |
| `DEMO_HUBS` | `on` | Bhilai's four hubs, each opened once if it is not there |
| `DEMO_SUPPLY` | `on` | Demo farms deliver to any hub nearly out of an item, every half hour |
| `DEMO_AUTOPACK` | `on` | An order no picker starts within 45 seconds is picked and packed by the app |
| `POOL_MAX_WAIT_MINUTES` | `0.5` | A lone packed order leaves after half a minute, not ten |
| `DELIVERY_CHECK_SECONDS` | `10` | The trip timer looks every ten seconds, not thirty |
| `AGENT_SELF_SIGNUP` | `on` | Anyone may sign in as a delivery agent and choose a hub |
| `OTP_MAX_PER_HOUR` | `15` | One phone playing customer and agent signs in again and again |
| `DEMO_HISTORY_ON_RESET` | `on` | `POST /v1/admin/reset` also writes 60 days of sales and some delivery lookups |
| `REPLENISHMENT_INTERVAL_MINUTES` | `15` | Packaged goods are reordered on a timer |

`app.yml` also sets the email backend (`ses`, from `no-reply@<domain>`), `FORWARDED_ALLOW_IPS` (below) and
`BACKGROUND_JOBS`, and passes the two secrets as `JWT_SECRET` and `DEMO_PASSWORD`.

**`POST /v1/admin/reset` on staging empties every table**: accounts, farms, orders and trips included, for everyone.
Do not use it there.

## The dev server

An EC2 machine named `farm2home-dev-server` in the same account and region, used for what the laptop cannot do. It
has no inbound network rule and no SSH key: it is reached only through AWS Systems Manager. Its id is not written
here; find it by name:

```powershell
aws ec2 describe-instances --filters "Name=tag:Name,Values=farm2home-dev-server" --query "Reservations[].Instances[].[InstanceId,State.Name]" --output text
aws ssm start-session --target <instance id>          # a shell (then: sudo -iu ec2-user); needs the Session Manager plugin
aws ec2 stop-instances --instance-ids <instance id>   # when work pauses for days; start-instances to bring it back
```

On it, as `ec2-user`: a clone of this repository in `~/app` with its own `.venv`; PostgreSQL with PostGIS in a
Docker container named `pg` on `127.0.0.1:5432` (test data only); Node 22, Playwright with Chromium, Java 17 and the
Android SDK. It is where these run:

| What | Command, from `~/app` | Notes |
| --- | --- | --- |
| The tests, by hand | `DARKSTORE_TEST_DB=postgresql://darkstore:darkstore@127.0.0.1:5432/darkstore .venv/bin/python -m pytest -q` | AWS (`test.ps1`) is the check that counts |
| The smoke test | `bash infra/smoke.sh https://staging.farm2home.galabavamsi.com` | It can reach staging when the laptop cannot |
| The end-to-end recording | `bash scripts/record_demo.sh` | An empty database, the API, the app's web builds, nine passes in a real browser from a farmer's listing to the customer's door; it remakes the report's screenshots. About ten minutes |
| The Android app | `API_URL=https://staging.farm2home.galabavamsi.com bash scripts/build_apk.sh` | [`mobile/README.md`](../mobile/README.md). About eleven minutes the first time, a few after |

Do not run the tests in `~/app` while a build is using that checkout. Files go between the dev server and the laptop
through the private artifacts bucket, with `aws s3 cp` or `aws s3 sync` on both sides; it empties itself after 30
days. Its name contains the account id, so it is not written here.

## Setting it up in a new account

Done once per AWS account, in this order. The domain's DNS must already be delegated to a Route 53 hosted zone; a
certificate for the domain and `*.<domain>` must be issued in the same region; and the domain must be a verified
identity in Amazon SES, with the account out of SES's sandbox, for sign-in codes to reach any address.

```powershell
# Where the app stack finds the domain, its hosted zone and the certificate (so the templates hold none of them)
aws ssm put-parameter --type String --name /farm2home/domain          --value <domain>
aws ssm put-parameter --type String --name /farm2home/hosted-zone-id  --value <zone id>
aws ssm put-parameter --type String --name /farm2home/certificate-arn --value <certificate arn>

aws cloudformation deploy --stack-name farm2home-network --template-file infra/network.yml --tags Project=farm2home
aws cloudformation deploy --stack-name farm2home-build   --template-file infra/build.yml   --tags Project=farm2home --capabilities CAPABILITY_NAMED_IAM
aws cloudformation deploy --stack-name farm2home-ci      --template-file infra/ci.yml      --tags Project=farm2home --capabilities CAPABILITY_NAMED_IAM
aws cloudformation deploy --stack-name farm2home-data-staging --template-file infra/data.yml --tags Project=farm2home Env=staging --parameter-overrides Env=staging
infra\deploy.ps1 -Env staging -Ref main
```

The database takes about 20 minutes to create. `aws cloudformation deploy` keeps a stack's earlier parameter values
unless `--parameter-overrides` gives new ones, even when a default in the template has changed. The client's real
address reaches the app because the container trusts `X-Forwarded-For` only from the VPC (`FORWARDED_ALLOW_IPS`), so
the per-address rate limit counts callers, not the load balancer.

## Taking it down

```powershell
aws cloudformation delete-stack --stack-name farm2home-app-staging
aws cloudformation delete-stack --stack-name farm2home-data-staging    # takes a final snapshot of the database
aws cloudformation delete-stack --stack-name farm2home-build           # empty the registry first
aws cloudformation delete-stack --stack-name farm2home-ci              # empty its copy of the PostGIS image first
aws cloudformation delete-stack --stack-name farm2home-network
```

Delete in that order: each stack uses values the one below it exports. The dev server, the bucket, the parameters,
the certificates and the hosted zone are not in the stacks and stay until removed by hand.

## What it costs

On-demand prices for Mumbai, from the AWS Price List API on 23 November 2026, in US dollars, while everything runs:

| Item | Per day |
| --- | --- |
| Database, `db.t4g.medium` with its standby, and 50 GB of storage | 4.45 |
| NAT gateway | 1.34 |
| Container, 0.5 vCPU and 1 GB | 0.62 |
| Load balancer | 0.57 |
| Three public IPv4 addresses | 0.36 |
| Firewall: one web ACL and four rules | 0.30 |
| Three secrets | 0.04 |
| **Staging, about** | **7.70** |
| Dev server, `m7i.xlarge`, while it runs (0.2121 an hour) | 5.21 |

About 13 dollars a day with the dev server running, before data transfer, logs and build minutes, which are small at
this size. The database with its standby is half of staging's cost. The hosted zone is 0.50 a month; map tiles and
email are charged per request and are cents at demo volume. The per-item prices are in
[`docs/journal/2026-11-23-staging-on-aws.md`](../docs/journal/2026-11-23-staging-on-aws.md). The budget on the
`Project=farm2home` tag sends email at 50% and 80% of actual spend and at 100% of the forecast. Stopping the dev
server is the quickest saving.
