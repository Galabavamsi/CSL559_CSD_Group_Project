# The tests move to AWS

*23 November 2026. GitHub stopped running our checks, so the checks moved to where the rest of the pipeline is.*

## Context

Tests ran in GitHub Actions on every pull request. During the day the repository was transferred to its new
owner's account, and from then on every run failed in three seconds with one line and no log:

```
The job was not started because your account is locked due to a billing issue.
```

Nothing in the code was wrong. The same commits passed on the project's dev server. But a pull request with a red
check that can never turn green is worse than one with no check: it teaches everyone to ignore red.

Builds and deployments already ran on AWS (`infra/build.yml`, `infra/deploy.ps1`). The tests now do too.

## What was built

| Piece | What it does |
| --- | --- |
| `infra/ci.yml` | A CodeBuild project, `farm2home-test`, and an image repository holding its own copy of the PostGIS image |
| `infra/ci-test.sh` | What a run does: start PostGIS in a container, install dependencies, check that the migrations build exactly the tables in `models.py`, syntax-check the demo pages' scripts, run the whole suite |
| `infra/test.ps1 -Ref <ref>` | Test one commit, wait, print the result, and set a commit status in GitHub so its pull request shows a check |
| `infra/deploy.ps1` | Now asks `test.ps1` first: a commit whose tests have not passed is not deployed |
| `.github/workflows/tests.yml` | Removed |

## Decisions, and why

**The checks are a script in the repository; the pipeline only calls it.** `ci-test.sh` is versioned with the code
it checks, so a change to how we test is reviewed like any other change, and the same script runs on any machine
with Docker. The CodeBuild project knows two things: how to get a commit, and to run that script.

**A test run is trusted with nothing.** It executes the code it is testing, and anyone who can push can change that
code. So its role can write its own logs and use one image repository, the PostGIS copy, and nothing else: not the
app, not the database, not the registry the app is deployed from, not a secret. The worst a bad push can do is
spoil the test database image.

**Our own copy of the PostGIS image.** The tests need `postgis/postgis`, which is on Docker Hub. Builds on AWS leave
from addresses shared with other customers, and Docker Hub limits anonymous downloads per address, so a run could
fail because of strangers' downloads. The first run pulled the image from Docker Hub and pushed it to our registry;
every run since takes it from there.

**The test database is the one a deployment would meet.** The image creates its database with a geocoder's tables
on the search path. That is what broke CI earlier in the day, and what a hand-made database on the dev server had
hidden. The script waits for the image's own initialisation to finish and tests against that database, with
durability switched off because it lives for one run.

**Pushes can start tests, never a build or a deployment.** With a GitHub connection authorised, every push starts
a test run and CodeBuild reports the result on the commit. A push still cannot build the app's image or deploy it;
a person signed in to AWS chooses the commit. Pull requests from forks do not start runs: that would be running a
stranger's code.

**A deployment waits for the tests.** `deploy.ps1` calls `test.ps1` for the exact commit. If that commit already
passed, the earlier run is used; otherwise it is tested first, and a failure stops the deployment. `-SkipTests`
exists for an emergency and prints a warning.

## What was checked

- The first run on AWS: 679 tests passed in 3 min 59 s; the whole run, with image copy and dependency install, took
  5 min 20 s. Its log shows every step, including "no copy yet: taking the image from Docker Hub and keeping one".
- The commit in GitHub shows "tests (AWS CodeBuild): success", and GitHub Actions ran nothing on it.
- Asking again for the same commit takes five seconds and reuses the run.
- A run that fails makes `test.ps1` exit with 1.
- A commit id that does not exist ends the run at the checkout (see the flaw below).
- A deployment to staging through the gate, of a commit not tested before: it ran the tests first (679 passed in
  3 min 40 s), then built the image, then rolled it out; nine minutes in all. The smoke test passed against the
  new version from outside.

## A flaw the checking found

To see a failure reported, we asked for a commit id that was mistyped. The run did fail, but for the wrong reason:
the checkout of the unknown commit failed, the build step carried on regardless, and it tried to test the
repository's default branch under the mistyped commit's name. Had the default branch been testable, a wrong
reference would have been reported as passing. The build step now stops at the first failed command, and a commit
that does not exist ends the run at the checkout.

## What it leaves open

- Runs start by hand until the GitHub connection is authorised in the AWS console, which only the account owner
  can do.
- The three older pull requests in the stack were opened while GitHub Actions was failing, and their branches still
  contain the workflow file. They keep their dead red check until they are merged.
- The phone app has no checks in CI yet (type-check, bundling).
- What a run costs has not been measured.

## Sources

- GitHub Docs, "REST API endpoints for commit statuses" (states, who may set them):
  https://docs.github.com/en/rest/commits/statuses
- AWS CodeBuild, "Filter GitHub webhook events (CloudFormation)" (push events, filter groups):
  https://docs.aws.amazon.com/codebuild/latest/userguide/github-webhook-events-cfn.html
- AWS CodeBuild, "Available runtimes" (Python 3.12 on the Amazon Linux 2023 standard:5.0 image):
  https://docs.aws.amazon.com/codebuild/latest/userguide/available-runtimes.html
- AWS re:Post knowledge center, Docker Hub pull limits in CodeBuild:
  https://repost.aws/knowledge-center/codebuild-docker-pull-image-error
- Seen ourselves: the billing message, read from the failed job's annotation; every number under "What was
  checked", from the runs' own logs.
