param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("write", "valuation", "curves", "ui", "scraper", "governance")]
    [string]$TaskKind,

    [ValidateSet("read", "write")]
    [string]$Intent = "write",

    [string]$OutputPath = "tmp/project_context.json",

    [string[]]$LauncherCommand,

    [switch]$PrintContext,

    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$MaxEnvTextLength = 30000
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

$resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath
} else {
    Join-Path $repoRoot $OutputPath
}

$outputDir = Split-Path -Parent $resolvedOutput
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -Path $outputDir -ItemType Directory | Out-Null
}

$bootstrapArgs = @(
    "scripts/project_memory.py",
    "build-context",
    "--task-kind", $TaskKind,
    "--intent", $Intent,
    "--output", $resolvedOutput
)

Push-Location $repoRoot
try {
    & $pythonPath @bootstrapArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Project-memory bootstrap failed for task kind '$TaskKind' with intent '$Intent'."
    }

    if (-not (Test-Path $resolvedOutput)) {
        throw "Expected context output was not created: $resolvedOutput"
    }

    $context = Get-Content $resolvedOutput -Raw | ConvertFrom-Json
    if (-not $context) {
        throw "Context JSON could not be parsed from $resolvedOutput"
    }

    $sessionMarkdown = [string]$context.session_context_markdown
    if (-not $sessionMarkdown.Trim()) {
        throw "Context bundle does not include session_context_markdown."
    }

    $markdownPath = [System.IO.Path]::ChangeExtension($resolvedOutput, ".md")
    Set-Content -LiteralPath $markdownPath -Value $sessionMarkdown -Encoding UTF8

    $env:AUTOSNIPER_PROJECT_CONTEXT_PATH = $resolvedOutput
    $env:AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN_PATH = $markdownPath
    $env:AUTOSNIPER_PROJECT_TASK_KIND = $TaskKind
    $env:AUTOSNIPER_PROJECT_INTENT = $Intent
    if ($sessionMarkdown.Length -le $MaxEnvTextLength) {
        $env:AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN = $sessionMarkdown
    }
    else {
        Remove-Item Env:AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN -ErrorAction SilentlyContinue
        Write-Host "[autosniper-ai] context markdown is large; use AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN_PATH instead of the raw env var."
    }

    Write-Host "[autosniper-ai] bootstrap OK"
    Write-Host "[autosniper-ai] context path: $resolvedOutput"
    Write-Host "[autosniper-ai] markdown path: $markdownPath"

    if ($PrintContext) {
        Write-Host ""
        Write-Host "----- BEGIN SESSION CONTEXT -----"
        Write-Host $sessionMarkdown
        Write-Host "----- END SESSION CONTEXT -----"
        Write-Host ""
    }

    if ($NoLaunch -or -not $LauncherCommand -or $LauncherCommand.Count -eq 0) {
        Write-Host "[autosniper-ai] no launcher command provided. Bootstrap only."
        Write-Host "[autosniper-ai] downstream launcher should read AUTOSNIPER_PROJECT_CONTEXT_PATH or AUTOSNIPER_PROJECT_CONTEXT_MARKDOWN_PATH."
        exit 0
    }

    Write-Host "[autosniper-ai] launching: $($LauncherCommand -join ' ')"
    if ($LauncherCommand.Count -eq 1) {
        & $LauncherCommand[0]
    }
    else {
        & $LauncherCommand[0] $LauncherCommand[1..($LauncherCommand.Count - 1)]
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
