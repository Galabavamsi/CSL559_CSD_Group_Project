<#
.SYNOPSIS
  Build one commit of the repository and run it in an environment on AWS.

.DESCRIPTION
  1. Finds the commit a branch, tag or commit id names in the public repository.
  2. Makes sure that commit's tests have passed on AWS (infra\test.ps1), running them if they have not been run.
     A commit whose tests fail is not deployed. -SkipTests is for an emergency, and says so loudly.
  3. Has CodeBuild build that commit's image and push it to the registry (skipped if it is already there).
  4. Updates the environment's app stack to run that image. ECS starts the new version, waits until the load
     balancer finds it healthy, then stops the old one; a version that never gets healthy is rolled back.

  Needs the AWS CLI signed in with rights to CodeBuild, ECR and CloudFormation in the account, and the network,
  data and build stacks already in place (infra/README.md).

.EXAMPLE
  infra\deploy.ps1 -Env staging -Ref main

.EXAMPLE
  infra\deploy.ps1 -Env staging -Ref f2h/some-branch
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet("staging", "prod")][string]$Env,
    [string]$Ref = "main",
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Which commit? A 40-character id is taken as it is; anything else is looked up in the repository.
$repo = aws codebuild batch-get-projects --names farm2home-build --query "projects[0].environment.environmentVariables[?name=='REPO_URL'].value | [0]" --output text
if ($Ref -match "^[0-9a-f]{40}$") { $sha = $Ref }
else {
    $found = git ls-remote $repo $Ref "refs/heads/$Ref" "refs/tags/$Ref" | Select-Object -First 1
    if (-not $found) { throw "No branch or tag '$Ref' in $repo" }
    $sha = ($found -split "\s+")[0]
}
$tag = $sha.Substring(0, 12)
Write-Host "Deploying $Ref = commit $sha to $Env (image tag $tag)"

# 2. Its tests must have passed. test.ps1 reuses a passing run of this exact commit, or runs one, and exits 1 on failure.
if ($SkipTests) { Write-Warning "Deploying $tag WITHOUT its tests having passed (-SkipTests)" }
else {
    & "$here\test.ps1" -Ref $sha
    if ($LASTEXITCODE -ne 0) { throw "Commit $tag did not pass its tests: not deployed" }
}

# 3. Build it, unless the registry already has it.
# Counted, not looked up by tag: looking up a tag that is not there is an error, and Windows PowerShell 5.1 turns a
# native command's redirected error output into a terminating one.
$built = aws ecr list-images --repository-name farm2home/api --filter tagStatus=TAGGED --query "length(imageIds[?imageTag=='$tag'])" --output text
if ($built -eq "1") { Write-Host "Image $tag is already in the registry" }
else {
    $build = aws codebuild start-build --project-name farm2home-build --environment-variables-override "name=GIT_REF,value=$sha" --query "build.id" --output text
    Write-Host "Building ($build) ..."
    do {
        Start-Sleep -Seconds 10
        $status = aws codebuild batch-get-builds --ids $build --query "builds[0].buildStatus" --output text
    } while ($status -eq "IN_PROGRESS")
    if ($status -ne "SUCCEEDED") {
        aws logs tail /farm2home/build --since 20m --format short | Select-Object -Last 40
        throw "Build $status"
    }
}

# 4. Run it, with the template of the commit being deployed and not the one in this folder. The folder may hold an
# edit that is still in progress, and that edit's settings must not ship with another commit's code (it nearly
# happened on 24 November). Written by cmd so the bytes are git's own: PowerShell 5.1 would re-encode them.
git -C $here fetch --quiet $repo $sha
$template = Join-Path ([IO.Path]::GetTempPath()) "farm2home-app-$tag.yml"
cmd /c "git -C `"$here`" show ${sha}:infra/app.yml > `"$template`""
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $template) -or (Get-Item $template).Length -eq 0) {
    throw "Could not read infra/app.yml of commit $tag"
}
aws cloudformation deploy --stack-name "farm2home-app-$Env" --template-file $template `
    --parameter-overrides "Env=$Env" "ImageTag=$tag" --capabilities CAPABILITY_NAMED_IAM `
    --tags Project=farm2home "Env=$Env" --no-fail-on-empty-changeset
if ($LASTEXITCODE -ne 0) {
    aws cloudformation describe-stack-events --stack-name "farm2home-app-$Env" `
        --query "StackEvents[?contains(ResourceStatus,'FAILED')].[LogicalResourceId,ResourceStatusReason]" --output text | Select-Object -First 10
    throw "The app stack did not deploy"
}
$url = aws cloudformation describe-stacks --stack-name "farm2home-app-$Env" --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue | [0]" --output text
Write-Host "Running at $url"
# Windows PowerShell 5.1 offers TLS 1.0 unless told otherwise, and the load balancer accepts 1.2 and 1.3 only.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { Write-Host ("Health: " + (Invoke-RestMethod "$url/health" -TimeoutSec 20 | ConvertTo-Json -Compress)) }
catch { Write-Host "Health check from this machine failed: $($_.Exception.Message)" }
