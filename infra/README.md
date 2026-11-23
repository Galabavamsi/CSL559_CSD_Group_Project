# Running on AWS

Five CloudFormation templates, deployed with the AWS CLI. Nothing here needs Node, CDK or Terraform.

| Stack | Template | What it holds | How many |
| --- | --- | --- | --- |
| `farm2home-network` | `network.yml` | VPC over two availability zones: public subnets (load balancer, NAT gateway), private subnets (containers), isolated subnets (database) | one |
| `farm2home-build` | `build.yml` | Container registry (ECR) and a CodeBuild project that builds one chosen commit | one |
| `farm2home-ci` | `ci.yml` | A CodeBuild project that tests one commit against PostGIS in a container, and its own copy of the PostGIS image | one |
| `farm2home-data-<env>` | `data.yml` | PostgreSQL 16 on RDS with a standby in a second zone; its security groups | one per environment |
| `farm2home-app-<env>` | `app.yml` | The API on ECS Fargate, HTTPS load balancer, web application firewall, DNS name, generated secrets | one per environment |

Environments are `staging` (at `staging.<domain>`) and `prod` (at `<domain>`). Every resource is tagged
`Project=farm2home`.

## Testing a commit

```powershell
infra\test.ps1 -Ref f2h/some-branch
```

Runs `infra/ci-test.sh` for that commit in CodeBuild: PostgreSQL with PostGIS in a container, the migration check,
a syntax check of the demo pages' scripts, a type-check of the phone app, and the whole test suite. It takes about four minutes, prints the result,
and sets a commit status in GitHub (through the `gh` CLI you are signed in to), so the commit's pull request shows
a check named "tests (AWS CodeBuild)". A commit that already passed is not run again unless you add `-Rerun`.

A test run is trusted with nothing but its own logs and its copy of the PostGIS image. It runs the code it is
testing, so it has no way to reach the app, its database, its registry or any secret.

**Runs started by a push.** Give the stack an authorised connection to GitHub and every push starts a run, with
the result reported on the commit by CodeBuild itself:

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

`-Ref` is a branch, a tag or a full commit id. The script finds the commit, makes sure its tests have passed on AWS
(running them if not, and stopping if they fail), has CodeBuild build its image (unless the registry already has
it), and updates the app stack to run it. ECS starts the new version, waits for the load
balancer to find it healthy, then stops the old one. A version that never gets healthy is rolled back.

To go back to an earlier version, deploy its commit again: its image is still in the registry.

**Why deploys start from AWS, not from a push to GitHub.** The repository is public. A push can start a test run,
which is trusted with nothing; it cannot start a build of the image or a deployment. Someone signed in to AWS
chooses a commit and deploys it. The image build can do one thing in the account: push an image to the registry.

## First-time set-up

Done once per AWS account, in this order. The domain's DNS must already be delegated to a Route 53 hosted zone, and
a certificate for the domain and `*.<domain>` must be issued in the same region.

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
unless `--parameter-overrides` gives new ones, even when a default in the template has changed.

## Things to know

- **Staff password.** The built-in `demo` password is public, so each environment gets its own, generated into
  Secrets Manager as `farm2home/<env>/staff-password`. The demo pages ask for it the first time a login is refused.
  Read it with `aws secretsmanager get-secret-value --secret-id farm2home/staging/staff-password --query SecretString --output text`.
- **Database password.** RDS creates it, keeps it in Secrets Manager and changes it every seven days. The app reads
  it whenever it opens a connection (`DB_SECRET_ARN`), so a change needs no restart.
- **One copy of the API.** `DesiredCount` stays 1 until the timed jobs and the live event feed are moved out of the
  API process; see the parameter's description in `app.yml`.
- **Client addresses.** The container trusts `X-Forwarded-For` only from the VPC (`FORWARDED_ALLOW_IPS`), so the
  app's per-address rate limit sees the caller's real address.
- **Logs.** `aws logs tail /farm2home/staging/api --follow`
- **A shell in the running container.**
  `aws ecs execute-command --cluster farm2home-staging --task <task id> --container api --interactive --command /bin/sh`
  (needs the Session Manager plugin for the AWS CLI).

## Taking it down

```powershell
aws cloudformation delete-stack --stack-name farm2home-app-staging
aws cloudformation delete-stack --stack-name farm2home-data-staging    # takes a final snapshot of the database
aws cloudformation delete-stack --stack-name farm2home-build           # empty the registry first
aws cloudformation delete-stack --stack-name farm2home-ci              # empty its copy of the PostGIS image first
aws cloudformation delete-stack --stack-name farm2home-network
```

Delete in that order: each stack uses values the one below it exports.

## What it costs

Rough figures for Mumbai while everything runs, staging only: the database with its standby is the largest part,
then the NAT gateway and the load balancer, then the container and the firewall. See
`docs/journal/2026-11-23-staging-on-aws.md` for the numbers and where they come from.
