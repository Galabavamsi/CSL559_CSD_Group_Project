<#
.SYNOPSIS
  Run the migration check and the test suite for one commit on AWS, and show the result on the commit in GitHub.

.DESCRIPTION
  1. Finds the commit a branch, tag or commit id names in the public repository.
  2. Unless -Rerun is given, looks for a run of exactly that commit that already passed, and uses it.
  3. Otherwise starts the farm2home-test CodeBuild project for it and waits (about five minutes).
  4. Prints the end of the run's log, and sets a commit status in GitHub with the `gh` CLI you are signed in to,
     so the commit's pull request shows a check. -NoStatus skips that.

  Exits 0 if the tests passed and 1 if they did not, so another script can depend on it (infra\deploy.ps1 does).
  Needs the AWS CLI signed in, and the farm2home-ci stack (infra/README.md).

.EXAMPLE
  infra\test.ps1 -Ref f2h/some-branch
#>
param(
    [string]$Ref = "main",
    [switch]$Rerun,
    [switch]$NoStatus
)
$ErrorActionPreference = "Stop"
$project = "farm2home-test"
$context = "tests (AWS CodeBuild)"

$repoUrl = aws codebuild batch-get-projects --names $project --query "projects[0].environment.environmentVariables[?name=='REPO_URL'].value | [0]" --output text
if (-not $repoUrl -or $repoUrl -eq "None") { throw "The $project project was not found. Deploy infra/ci.yml first (infra/README.md)." }
if ($Ref -match "^[0-9a-f]{40}$") { $sha = $Ref }
else {
    $found = git ls-remote $repoUrl $Ref "refs/heads/$Ref" "refs/tags/$Ref" | Select-Object -First 1
    if (-not $found) { throw "No branch or tag '$Ref' in $repoUrl" }
    $sha = ($found -split "\s+")[0]
}
$repo = ($repoUrl -replace "^https://github.com/", "") -replace "\.git$", ""

function Set-Status([string]$State, [string]$Description) {
    if ($NoStatus) { return }
    if ($Description.Length -gt 140) { $Description = $Description.Substring(0, 137) + "..." }
    gh api "repos/$repo/statuses/$sha" -f "state=$State" -f "context=$context" -f "description=$Description" --silent
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not set the commit status in GitHub (is 'gh' signed in with access to $repo?)" }
}

# 2. A run of this very commit that already passed is as good as a new one.
$build = $null
if (-not $Rerun) {
    $ids = aws codebuild list-builds-for-project --project-name $project --max-items 40 --query "ids" --output json | ConvertFrom-Json
    if ($ids) {
        $past = aws codebuild batch-get-builds --ids $ids --query "builds[?buildStatus=='SUCCEEDED'].{id:id,sha:resolvedSourceVersion,ref:environment.environmentVariables[?name=='GIT_REF'].value|[0]}" --output json | ConvertFrom-Json
        $build = ($past | Where-Object { $_.ref -eq $sha -or $_.sha -eq $sha } | Select-Object -First 1).id
        if ($build) { Write-Host "Commit $($sha.Substring(0,12)) already passed in run $build" }
    }
}

# 3. Otherwise run it.
if (-not $build) {
    # A project connected to GitHub checks the commit out itself and is told which one; a project with no source
    # of its own takes no source version and fetches the commit named in GIT_REF.
    $sourceType = aws codebuild batch-get-projects --names $project --query "projects[0].source.type" --output text
    $startArgs = @("codebuild", "start-build", "--project-name", $project, "--environment-variables-override", "name=GIT_REF,value=$sha", "--query", "build.id", "--output", "text")
    if ($sourceType -ne "NO_SOURCE") { $startArgs += @("--source-version", $sha) }
    $build = & aws @startArgs
    if (-not $build) { throw "The test run could not be started" }
    Write-Host "Testing $Ref = $($sha.Substring(0,12)) in run $build ..."
    Set-Status "pending" "Running on AWS"
    do {
        Start-Sleep -Seconds 15
        $status = aws codebuild batch-get-builds --ids $build --query "builds[0].buildStatus" --output text
    } while ($status -eq "IN_PROGRESS")
}
else { $status = "SUCCEEDED" }

# 4. Say what happened.
$info = aws codebuild batch-get-builds --ids $build --query "builds[0].{stream:logs.streamName,start:startTime,end:endTime}" --output json | ConvertFrom-Json
$log = @()
if ($info.stream) {
    $log = aws logs get-log-events --log-group-name /farm2home/test --log-stream-name $info.stream --limit 400 --query "events[].message" --output json | ConvertFrom-Json
    $log = $log | ForEach-Object { $_.TrimEnd() } | Where-Object { $_ }
}
$summary = ($log | Where-Object { $_ -match "^\d+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|^FAILED |^ERROR " } | Select-Object -Last 12)
$summary | ForEach-Object { Write-Host "  $_" }
$verdict = ($log | Where-Object { $_ -match "\d+ (passed|failed)" } | Select-Object -Last 1)
if ($verdict) { $verdict = ($verdict -replace "=", "").Trim() }

if ($status -eq "SUCCEEDED") {
    if (-not $verdict) { $verdict = "passed" }
    Write-Host "PASSED: $verdict"
    Set-Status "success" $verdict
    exit 0
}
if (-not $summary) {      # it failed before the tests ran: show what it was doing, without CodeBuild's own chatter
    $log | Where-Object { $_ -notmatch "^\[Container\]" } | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" }
}
if (-not $verdict) { $verdict = "the run ended $status before the tests reported" }
Write-Host "FAILED ($status): $verdict"
Set-Status "failure" $verdict
exit 1
