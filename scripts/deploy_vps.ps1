param(
    [string]$VpsHost = "134.199.144.141",
    [string]$VpsUser = "root",
    [string]$KeyPath = (Join-Path $env:USERPROFILE ".ssh\autosniper_digitalocean"),
    [string]$RemoteRoot = "/opt/autosniper",
    [switch]$DryRun,
    [switch]$SkipLocalValidation,
    [switch]$DeployCommittedHead,
    [switch]$Release,
    [switch]$Push,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $repoRoot "venv\Scripts\python.exe"
$requiredLocalPaths = @(
    "app.py",
    "requirements.txt",
    ".streamlit\config.toml",
    "assets",
    "autotrader_isolated",
    "config",
    "governance",
    "jobs",
    "ops",
    "pages",
    "scripts",
    "shared"
)
$optionalLocalPaths = @(
    "DASHBOARD.py",
    "status_app.py",
    "pyproject.toml"
)
$governedDataPaths = @(
    "CSV_data\restricted\curves.csv",
    "CSV_data\restricted\versions",
    "CSV_data\reports\repair_pricing_schedule.csv",
    "CSV_data\reports\repair_review_decisions.csv"
)
$productionBranch = "main"

function Assert-SafeConfiguration {
    if ($VpsHost -notmatch "^[A-Za-z0-9.-]+$") {
        throw "VpsHost contains unsupported characters: $VpsHost"
    }
    if ($VpsUser -notmatch "^[A-Za-z_][A-Za-z0-9_-]*$") {
        throw "VpsUser contains unsupported characters: $VpsUser"
    }
    if ($RemoteRoot -notmatch "^/[A-Za-z0-9._/-]+$") {
        throw "RemoteRoot must be an absolute Linux path containing only safe path characters."
    }
    if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
        throw "SSH key not found: $KeyPath"
    }
    $pathsToCheck = @($requiredLocalPaths)
    if ($Release) {
        $pathsToCheck += $governedDataPaths
    }
    foreach ($relativePath in $pathsToCheck) {
        $fullPath = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            throw "Required deployment path is missing: $relativePath"
        }
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Label,
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Assert-SafeConfiguration

$deployPaths = @($requiredLocalPaths)
foreach ($relativePath in $optionalLocalPaths) {
    if (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath)) {
        $deployPaths += $relativePath
    }
}
if ($Release) {
    $deployPaths += $governedDataPaths
}
$gitDeployPaths = @($deployPaths | ForEach-Object { $_ -replace "\\", "/" })
$commitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commitSha -notmatch "^[0-9a-f]{40}$") {
    throw "Unable to resolve the current Git commit."
}
$currentBranch = (& git -C $repoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to resolve the current Git branch."
}
if ($Release) {
    if ($Force) {
        throw "-Force cannot be used for a governed production release."
    }
    if ($DeployCommittedHead) {
        throw "-DeployCommittedHead cannot be used for a governed production release. Release paths must be clean."
    }
    if ($Push) {
        throw "Push the reviewed commit first, then run -Release from the synchronized main branch."
    }
    if ($currentBranch -ne $productionBranch) {
        throw "Production releases must run from branch '$productionBranch'; current branch is '$currentBranch'."
    }
    $remoteMainLine = @(& git -C $repoRoot ls-remote origin "refs/heads/$productionBranch")
    if ($LASTEXITCODE -ne 0 -or $remoteMainLine.Count -ne 1) {
        throw "Unable to verify origin/$productionBranch."
    }
    $remoteMainSha = ($remoteMainLine[0] -split "\s+")[0]
    if ($remoteMainSha -ne $commitSha) {
        throw "Release stopped: local HEAD $commitSha does not match origin/$productionBranch $remoteMainSha."
    }
}
$dirtyDeployPaths = @(& git -C $repoRoot status --porcelain -- @gitDeployPaths)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect the deployment working tree."
}
if ($dirtyDeployPaths.Count -gt 0 -and ($Release -or -not $DeployCommittedHead)) {
    Write-Host "Uncommitted deployable files:"
    $dirtyDeployPaths | ForEach-Object { Write-Host "  $_" }
    if ($Release) {
        throw "A production release requires clean code, configuration, curve, and repair-decision paths."
    }
    throw "Commit the intended application changes before deployment. Use -DeployCommittedHead only to deploy HEAD while intentionally ignoring these working-tree edits."
}

$deploymentKind = if ($Release) { "governed production release" } else { "code deployment" }
Write-Host "AutoSniper VPS $deploymentKind"
Write-Host "  Source: $repoRoot"
Write-Host "  Commit: $commitSha"
Write-Host "  Target: ${VpsUser}@${VpsHost}:$RemoteRoot"
Write-Host "  Included: $($deployPaths -join ', ')"
if ($Release) {
    Write-Host "  Governed data: curves/version history, repair pricing, and approved repair decisions"
    Write-Host "  Protected runtime: scraper CSVs, live repair queue, valuations, artifacts, logs, output, status, and virtual environments"
} else {
    Write-Host "  Protected: CSV_data, curves, artifacts, logs, output, outputs, status, and virtual environments"
}

if (-not $SkipLocalValidation) {
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Local Python environment not found: $pythonPath"
    }
    Write-Host "Running local Python compile validation..."
    Push-Location $repoRoot
    try {
        Invoke-CheckedCommand -Label "Local Python validation" -Command {
            & $pythonPath -m compileall -q app.py pages shared scripts ops jobs governance autotrader_isolated
        }
        if ($Release) {
            Write-Host "Validating governed release inputs..."
            Invoke-CheckedCommand -Label "Governed release validation" -Command {
                & $pythonPath scripts\vps_release_manifest.py --root $repoRoot --commit $commitSha
            }
        }
    } finally {
        Pop-Location
    }
}

if ($DryRun) {
    Write-Host "Dry run complete. No archive was created and nothing was changed on the VPS."
    exit 0
}

$deployId = Get-Date -Format "yyyyMMddTHHmmss"
$archivePath = Join-Path ([System.IO.Path]::GetTempPath()) "autosniper-code-$deployId.tar.gz"
$remoteArchive = "/tmp/autosniper-code-$deployId.tar.gz"
$target = "${VpsUser}@${VpsHost}"

try {
    $archiveLabel = if ($Release) { "code and governed-data release" } else { "code-only deployment" }
    Write-Host "Packaging $archiveLabel archive..."
    $archiveArguments = @(
        "-C", $repoRoot,
        "archive",
        "--format=tar.gz",
        "--output=$archivePath",
        "HEAD",
        "--"
    ) + $gitDeployPaths
    Invoke-CheckedCommand -Label "Archive creation" -Command {
        & git @archiveArguments
    }

    $archiveSizeMb = [math]::Round((Get-Item -LiteralPath $archivePath).Length / 1MB, 2)
    Write-Host "Uploading $archiveSizeMb MB..."
    Invoke-CheckedCommand -Label "Archive upload" -Command {
        & scp -q -i $KeyPath $archivePath "${target}:$remoteArchive"
    }

    $remoteScript = @'
set -euo pipefail

archive="$1"
root="$2"
deploy_id="$3"
force="$4"
commit_sha="$5"
release="$6"
stage="/tmp/autosniper-stage-$deploy_id"
backup_dir="/opt/autosniper-deploy-backups"
backup="$backup_dir/pre-$deploy_id.tar.gz"
governed_backup="$backup_dir/governed-pre-$deploy_id.tar.gz"
daily_timer_was_active=0
hourly_timer_was_active=0
rollback_needed=0

cleanup() {
    if [[ "$daily_timer_was_active" == "1" ]]; then
        systemctl start autosniper-daily.timer || true
    fi
    if [[ "$hourly_timer_was_active" == "1" ]]; then
        systemctl start autosniper-hourly.timer || true
    fi
    rm -rf "$stage"
    rm -f "$archive"
}
trap cleanup EXIT

restore_previous() {
    set +e
    echo "Restoring the previous AutoSniper release."
    tar -xzf "$backup" -C "$root"
    if [[ "$release" == "1" && -f "$governed_backup" ]]; then
        rm -f \
            "$root/CSV_data/restricted/curves.csv" \
            "$root/CSV_data/reports/repair_pricing_schedule.csv" \
            "$root/CSV_data/reports/repair_review_decisions.csv"
        rm -rf "$root/CSV_data/restricted/versions"
        tar -xzf "$governed_backup" -C "$root"
    fi
    chown -R autosniper:autosniper "$root"
    systemctl restart autosniper
    set -e
}

on_error() {
    exit_code="$?"
    trap - ERR
    if [[ "$rollback_needed" == "1" ]]; then
        restore_previous
    fi
    exit "$exit_code"
}
trap on_error ERR

if [[ "$release" == "1" ]]; then
    if systemctl is-active --quiet autosniper-daily.timer; then
        daily_timer_was_active=1
        systemctl stop autosniper-daily.timer
    fi
    if systemctl is-active --quiet autosniper-hourly.timer; then
        hourly_timer_was_active=1
        systemctl stop autosniper-hourly.timer
    fi
fi

if [[ "$force" != "1" ]]; then
    active_jobs="$(systemctl list-units --state=activating,running --plain --no-legend 'autosniper-job@*.service' || true)"
    if [[ -n "$active_jobs" ]]; then
        echo "A scheduled AutoSniper job is running. Deployment stopped to protect the live pipeline."
        echo "$active_jobs"
        exit 20
    fi
fi

mkdir -p "$stage" "$backup_dir"
tar -xzf "$archive" -C "$stage"

"$root/.venv/bin/python" -m compileall -q \
    "$stage/app.py" \
    "$stage/pages" \
    "$stage/shared" \
    "$stage/scripts" \
    "$stage/ops" \
    "$stage/jobs" \
    "$stage/governance" \
    "$stage/autotrader_isolated"

if [[ "$release" == "1" ]]; then
    "$root/.venv/bin/python" "$stage/scripts/vps_release_manifest.py" \
        --root "$stage" \
        --commit "$commit_sha"
fi

tar \
    --exclude='./.venv' \
    --exclude='./CSV_data' \
    --exclude='./curves' \
    --exclude='./artifacts' \
    --exclude='./logs' \
    --exclude='./output' \
    --exclude='./outputs' \
    --exclude='./status' \
    --exclude='./tmp' \
    --exclude='./__pycache__' \
    -czf "$backup" -C "$root" .

if [[ "$release" == "1" ]]; then
    tar -czf "$governed_backup" -C "$root" \
        CSV_data/restricted/curves.csv \
        CSV_data/restricted/versions \
        CSV_data/reports/repair_pricing_schedule.csv \
        CSV_data/reports/repair_review_decisions.csv
fi
rollback_needed=1

if ! cmp -s "$stage/requirements.txt" "$root/requirements.txt"; then
    echo "Installing changed Python requirements..."
    "$root/.venv/bin/pip" install -r "$stage/requirements.txt"
fi

if [[ "$release" == "1" ]]; then
    systemctl stop autosniper
fi

cp -a "$stage/." "$root/"
chown -R autosniper:autosniper "$root"

if [[ "$release" == "1" ]]; then
    (
        cd "$root"
        "$root/.venv/bin/python" scripts/vps_release_manifest.py \
            --root "$root" \
            --commit "$commit_sha"
        "$root/.venv/bin/python" scripts/governance_checks.py check
        "$root/.venv/bin/python" scripts/readiness_smoke.py
    )
fi

if ! systemctl restart autosniper; then
    echo "Restart failed; restoring the previous source snapshot."
    restore_previous
    rollback_needed=0
    exit 21
fi

healthy=0
for _ in {1..20}; do
    if curl -fs http://127.0.0.1:8501/_stcore/health | grep -qx "ok"; then
        healthy=1
        break
    fi
    sleep 1
done

if [[ "$healthy" != "1" ]]; then
    echo "Health check failed; restoring the previous source snapshot."
    restore_previous
    rollback_needed=0
    exit 22
fi

mkdir -p "$root/status"
if [[ "$release" == "1" ]]; then
    "$root/.venv/bin/python" "$root/scripts/vps_release_manifest.py" \
        --root "$root" \
        --commit "$commit_sha" \
        --write "$root/status/governed_data_release.json"
fi
printf '%s\n' "$commit_sha" > "$root/status/deployed_commit.txt"
chown autosniper:autosniper "$root/status/deployed_commit.txt"
if [[ -f "$root/status/governed_data_release.json" ]]; then
    chown autosniper:autosniper "$root/status/governed_data_release.json"
fi
rollback_needed=0

find "$backup_dir" -maxdepth 1 -type f -name 'pre-*.tar.gz' -printf '%T@ %p\n' \
    | sort -nr \
    | tail -n +6 \
    | cut -d' ' -f2- \
    | xargs -r rm -f
find "$backup_dir" -maxdepth 1 -type f -name 'governed-pre-*.tar.gz' -printf '%T@ %p\n' \
    | sort -nr \
    | tail -n +6 \
    | cut -d' ' -f2- \
    | xargs -r rm -f

echo "DEPLOY_OK $deploy_id"
echo "Commit: $commit_sha"
echo "Health: $(curl -fsS http://127.0.0.1:8501/_stcore/health)"
echo "Service: $(systemctl is-active autosniper)"
if [[ "$release" == "1" ]]; then
    echo "Governed data: $root/status/governed_data_release.json"
fi
'@

    $remoteScriptBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
    $forceFlag = if ($Force) { "1" } else { "0" }
    $releaseFlag = if ($Release) { "1" } else { "0" }
    $remoteCommand = "echo '$remoteScriptBase64' | base64 -d | bash -s -- '$remoteArchive' '$RemoteRoot' '$deployId' '$forceFlag' '$commitSha' '$releaseFlag'"

    Write-Host "Validating and activating the staged deployment..."
    Invoke-CheckedCommand -Label "Remote deployment" -Command {
        & ssh -i $KeyPath $target $remoteCommand
    }

    Write-Host "Deployment completed successfully."
    Write-Host "Live AI Analysis: http://$VpsHost/AI_ANALYSIS"
    if ($Push) {
        Write-Host "Pushing the deployed commit to the configured upstream..."
        Invoke-CheckedCommand -Label "Git push" -Command {
            & git -C $repoRoot push
        }
    }
} finally {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
}
