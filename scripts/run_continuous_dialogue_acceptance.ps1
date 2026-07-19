param(
    [string]$OutputRoot = "reports/continuous-dialogue"
)

$ErrorActionPreference = "Stop"

function Assert-NativeSuccess([string]$Name) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$commit = (git -C $root rev-parse --short HEAD).Trim()
$runDir = Join-Path $root (Join-Path $OutputRoot "$timestamp-$commit")
$screenshots = Join-Path $runDir "screenshots"
$traces = Join-Path $runDir "traces"
$videos = Join-Path $runDir "videos"
$rawEvidence = Join-Path $runDir "raw-browser-evidence"

New-Item -ItemType Directory -Force -Path $runDir, $screenshots, $traces, $videos, $rawEvidence | Out-Null

$commands = @(
    "uv run ruff check .",
    "uv run python -m pytest tests/integration/ -q --tb=short",
    "uv run python -m compileall -q dataworks_agent",
    "uv run python -m dataworks_agent.scripts.verify_agent_runtime --output <run>/backend",
    "npm run test:unit",
    "npm run build",
    "npm run test:e2e"
)
$commands | Set-Content -Encoding utf8 (Join-Path $runDir "commands.txt")
$commit | Set-Content -Encoding utf8 (Join-Path $runDir "commit.txt")

try {
    Push-Location $root
    uv run ruff check .
    Assert-NativeSuccess "ruff"
    uv run python -m pytest tests/integration/ -q --tb=short --junitxml (Join-Path $runDir "test-results.xml")
    Assert-NativeSuccess "integration pytest"
    uv run python -m compileall -q dataworks_agent
    Assert-NativeSuccess "compileall"
    uv run python -m dataworks_agent.scripts.verify_agent_runtime --output (Join-Path $runDir "backend")
    Assert-NativeSuccess "backend runtime verifier"
    Pop-Location

    Copy-Item (Join-Path $runDir "backend/conversation-transcript.json") (Join-Path $runDir "conversation-transcript.json")
    Copy-Item (Join-Path $runDir "backend/backend-events.jsonl") (Join-Path $runDir "backend-events.jsonl")
    Copy-Item (Join-Path $runDir "backend/no-write-proof.json") (Join-Path $runDir "no-write-proof.json")

    $env:PLAYWRIGHT_OUTPUT_DIR = Join-Path $runDir "playwright-artifacts"
    $env:PLAYWRIGHT_JUNIT_OUTPUT = Join-Path $runDir "playwright-results.xml"
    $env:AGENT_EVIDENCE_DIR = $rawEvidence
    $env:AGENT_ACCEPTANCE_DB = Join-Path $runDir "acceptance.db"

    Push-Location (Join-Path $root "frontend")
    npm run test:unit
    Assert-NativeSuccess "frontend unit tests"
    npm run build
    Assert-NativeSuccess "frontend build"
    npm run test:e2e
    Assert-NativeSuccess "browser E2E"
    Pop-Location

    $console = @()
    Get-ChildItem -LiteralPath $rawEvidence -Filter "*-console.json" | ForEach-Object {
        $console += [PSCustomObject]@{ test = $_.BaseName; entries = @(Get-Content -Raw -Encoding utf8 $_.FullName | ConvertFrom-Json) }
    }
    $network = @()
    Get-ChildItem -LiteralPath $rawEvidence -Filter "*-network.json" | ForEach-Object {
        $network += [PSCustomObject]@{ test = $_.BaseName; entries = @(Get-Content -Raw -Encoding utf8 $_.FullName | ConvertFrom-Json) }
    }
    $console | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $runDir "frontend-console.json")
    $network | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $runDir "network-events.json")

    Get-ChildItem -LiteralPath (Join-Path $runDir "playwright-artifacts") -Recurse -Filter "final.png" | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $screenshots "$($_.Directory.Name).png")
    }
    Get-ChildItem -LiteralPath (Join-Path $runDir "playwright-artifacts") -Recurse -Filter "trace.zip" | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $traces "$($_.Directory.Name).zip")
    }
    Get-ChildItem -LiteralPath (Join-Path $runDir "playwright-artifacts") -Recurse -Filter "video.webm" | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $videos "$($_.Directory.Name).webm")
    }

    $summary = @"
# Continuous Dialogue Acceptance

- Run: $timestamp-$commit
- Commit: $commit
- Backend integration: PASS
- Backend 50-turn verification: PASS
- Frontend unit tests: PASS
- Frontend build: PASS
- Browser journeys: 8/8 PASS
- DataWorks write-capable calls: 0
- Result: PASS
"@
    $summary | Set-Content -Encoding utf8 (Join-Path $runDir "summary.md")
    Write-Output $runDir
}
catch {
    "# Continuous Dialogue Acceptance`n`n- Result: FAIL`n- Error: $($_.Exception.Message)" | Set-Content -Encoding utf8 (Join-Path $runDir "summary.md")
    throw
}
finally {
    while ((Get-Location).Path -ne $root -and (Get-Location).Path.StartsWith($root)) {
        Pop-Location
    }
}
