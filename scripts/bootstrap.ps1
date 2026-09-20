param(
  [switch]$ProductionOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "=== Section 35.1: Bootstrap Process ===" -ForegroundColor Cyan

# 1. Verify Python 3.11 and uv
Write-Host "[1/6] Verifying Python 3.11 and uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "FATAL: 'uv' is required but was not found on PATH."
}

$pyVersion = uv run python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
if ($pyVersion.Trim() -ne "3.11") {
  throw "FATAL: Python 3.11 is required by Section 35.1, but found Python $pyVersion"
}
Write-Host "  -> Python $pyVersion and uv verified." -ForegroundColor Green

# 2. Create or update the project environment from uv.lock
Write-Host "[2/6] Updating environment from uv.lock..."
if ($ProductionOnly) {
  uv sync --locked
} else {
  uv sync --locked --extra dev
}
Write-Host "  -> Dependencies synced from uv.lock." -ForegroundColor Green

# 3. Verify required directories and environment variables
Write-Host "[3/6] Verifying required directories and environment variables..."
$requiredDirs = @(
  (Join-Path $projectRoot "data"),
  (Join-Path $projectRoot "data\logs"),
  (Join-Path $projectRoot "data\backups"),
  (Join-Path $projectRoot "data\raw_archive"),
  (Join-Path $projectRoot "data\manual_drop"),
  (Join-Path $projectRoot "configs"),
  (Join-Path $projectRoot "docs\runbooks")
)
foreach ($dir in $requiredDirs) {
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "  -> Created directory: $dir"
  }
}
Write-Host "  -> All required directories verified." -ForegroundColor Green

# 4. Run database migrations
Write-Host "[4/6] Running database migrations..."
uv run qual-engine initialise-db
if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE" }
Write-Host "  -> Database initialised and migrations applied." -ForegroundColor Green

# 5. Run environment verification and smoke test
Write-Host "[5/6] Running environment verification..."
uv run qual-engine verify-environment
if ($LASTEXITCODE -ne 0) { throw "Environment verification failed with exit code $LASTEXITCODE" }
Write-Host "  -> Environment verified." -ForegroundColor Green

Write-Host "[6/6] Running bootstrap smoke test..."
uv run pytest tests/test_smoke.py -q
if ($LASTEXITCODE -ne 0) { throw "Smoke test failed with exit code $LASTEXITCODE" }
Write-Host "  -> Smoke test passed." -ForegroundColor Green

Write-Host "=== Bootstrap successfully completed! ===" -ForegroundColor Green
