param(
    [string]$VpsHost = "134.199.144.141",
    [string]$VpsUser = "root",
    [string]$KeyPath = (Join-Path $env:USERPROFILE ".ssh\autosniper_digitalocean"),
    [string]$RemoteRoot = "/opt/autosniper",
    [switch]$DryRun,
    [switch]$SkipLocalValidation,
    [switch]$DeployCommittedHead,
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
    foreach ($relativePath in $requiredLocalPaths) {
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
$gitDeployPaths = @($deployPaths | ForEach-Object { $_ -replace "\\", "/" })
$commitSha = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commitSha -notmatch "^[0-9a-f]{40}$") {
    throw "Unable to resolve the current Git commit."
}
$dirtyDeployPaths = @(& git -C $repoRoot status --porcelain -- @gitDeployPaths)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect the deployment working tree."
}
if ($dirtyDeployPaths.Count -gt 0 -and -not $DeployCommittedHead) {
    Write-Host "Uncommitted deployable files:"
    $dirtyDeployPaths | ForEach-Object { Write-Host "  $_" }
    throw "Commit the intended application changes before deployment. Use -DeployCommittedHead only to deploy HEAD while intentionally ignoring these working-tree edits."
}

Write-Host "AutoSniper VPS code deployment"
Write-Host "  Source: $repoRoot"
Write-Host "  Commit: $commitSha"
Write-Host "  Target: ${VpsUser}@${VpsHost}:$RemoteRoot"
Write-Host "  Included: $($deployPaths -join ', ')"
Write-Host "  Protected: CSV_data, curves, artifacts, logs, output, outputs, status, and virtual environments"

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
    Write-Host "Packaging code-only deployment archive..."
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
stage="/tmp/autosniper-stage-$deploy_id"
backup_dir="/opt/autosniper-deploy-backups"
backup="$backup_dir/pre-$deploy_id.tar.gz"

cleanup() {
    rm -rf "$stage"
    rm -f "$archive"
}
trap cleanup EXIT

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

if ! cmp -s "$stage/requirements.txt" "$root/requirements.txt"; then
    echo "Installing changed Python requirements..."
    "$root/.venv/bin/pip" install -r "$stage/requirements.txt"
fi

cp -a "$stage/." "$root/"
chown -R autosniper:autosniper "$root"

if ! systemctl restart autosniper; then
    echo "Restart failed; restoring the previous source snapshot."
    tar -xzf "$backup" -C "$root"
    chown -R autosniper:autosniper "$root"
    systemctl restart autosniper
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
    tar -xzf "$backup" -C "$root"
    chown -R autosniper:autosniper "$root"
    systemctl restart autosniper
    exit 22
fi

mkdir -p "$root/status"
printf '%s\n' "$commit_sha" > "$root/status/deployed_commit.txt"
chown autosniper:autosniper "$root/status/deployed_commit.txt"

find "$backup_dir" -maxdepth 1 -type f -name 'pre-*.tar.gz' -printf '%T@ %p\n' \
    | sort -nr \
    | tail -n +6 \
    | cut -d' ' -f2- \
    | xargs -r rm -f

echo "DEPLOY_OK $deploy_id"
echo "Commit: $commit_sha"
echo "Health: $(curl -fsS http://127.0.0.1:8501/_stcore/health)"
echo "Service: $(systemctl is-active autosniper)"
'@

    $remoteScriptBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remoteScript))
    $forceFlag = if ($Force) { "1" } else { "0" }
    $remoteCommand = "echo '$remoteScriptBase64' | base64 -d | bash -s -- '$remoteArchive' '$RemoteRoot' '$deployId' '$forceFlag' '$commitSha'"

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
