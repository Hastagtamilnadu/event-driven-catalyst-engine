param(
  [Parameter(Mandatory = $true)]
  [ValidateSet(
    "QualEngine_Nightly",
    "QualEngine_Morning",
    "QualEngine_PreOpen",
    "QualEngine_Intraday",
    "QualEngine_Close",
    "QualEngine_MonthlyAudit",
    # Aliases for backward compatibility:
    "nightly", "morning", "preopen", "paper", "health"
  )]
  [string]$Job,
  [string]$RunId = [System.Guid]::NewGuid().ToString()
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# Resolve canonical job name
$canonicalJob = switch ($Job) {
  "nightly" { "QualEngine_Nightly" }
  "morning" { "QualEngine_Morning" }
  "preopen" { "QualEngine_PreOpen" }
  "paper"   { "QualEngine_Close" }
  "health"  { "QualEngine_Morning" }
  Default   { $Job }
}

# Setup dated log directory (§35.3)
$logRoot = "D:\02_Trading\data\logs"
$dateFolder = Join-Path $logRoot (Get-Date -Format "yyyy\\MM\\dd")
New-Item -ItemType Directory -Force -Path $dateFolder | Out-Null
$logFile = Join-Path $dateFolder "$canonicalJob.jsonl"

$startedUtc = [System.DateTime]::UtcNow.ToString("o")
Write-Host "[$startedUtc] Starting $canonicalJob (RunID: $RunId)..."

$logEntry = @{
  timestamp_utc = $startedUtc
  job = $canonicalJob
  run_id = $RunId
  status = "STARTED"
} | ConvertTo-Json -Compress
Add-Content -Path $logFile -Value $logEntry

try {
  switch ($canonicalJob) {
    "QualEngine_Nightly" {
      # Ingest all scheduled sources; archive and process events (§35.2)
      Write-Host "  -> Running event processing..."
      uv run qual-engine process-events
      if ($LASTEXITCODE -ne 0) { throw "process-events failed" }
    }
    "QualEngine_Morning" {
      # Refresh risk data, universe, actions, and source health (§35.2)
      Write-Host "  -> Running health and universe check..."
      uv run qual-engine health
      if ($LASTEXITCODE -ne 0) { throw "health check failed" }
    }
    "QualEngine_PreOpen" {
      # Create eligible paper intents only (§35.2)
      Write-Host "  -> Creating paper intents..."
      uv run qual-engine create-paper-intents
      if ($LASTEXITCODE -ne 0) { throw "create-paper-intents failed" }
    }
    "QualEngine_Intraday" {
      # Observe supported sources and process queued work (§35.2)
      Write-Host "  -> Running intraday observer and paper processing..."
      uv run qual-engine run-paper
      if ($LASTEXITCODE -ne 0) { throw "run-paper failed" }
    }
    "QualEngine_Close" {
      # Fills, marks, reconciliation, health report, and SQLite backup (§35.2, §35.3)
      Write-Host "  -> Running close processing..."
      uv run qual-engine run-paper
      if ($LASTEXITCODE -ne 0) { throw "run-paper failed" }
      uv run qual-engine report --report performance
      if ($LASTEXITCODE -ne 0) { throw "reconciliation report failed" }
      Write-Host "  -> Running SQLite backup API..."
      uv run python scripts/backup_db.py
      if ($LASTEXITCODE -ne 0) { throw "database backup failed" }
    }
    "QualEngine_MonthlyAudit" {
      # Model benchmark, source timing, strategy evidence (§35.2)
      Write-Host "  -> Running monthly audit benchmark..."
      uv run pytest tests/test_benchmarks.py -q
      if ($LASTEXITCODE -ne 0) { throw "monthly benchmark failed" }
    }
  }

  $finishedUtc = [System.DateTime]::UtcNow.ToString("o")
  # Heartbeat written ONLY after successful persistence (§35.2)
  $heartbeatFile = Join-Path "D:\02_Trading\data" "heartbeat_$canonicalJob.json"
  @{
    job = $canonicalJob
    run_id = $RunId
    last_successful_run_utc = $finishedUtc
    status = "HEALTHY"
  } | ConvertTo-Json | Set-Content -Path $heartbeatFile

  $successLog = @{
    timestamp_utc = $finishedUtc
    job = $canonicalJob
    run_id = $RunId
    status = "SUCCEEDED"
  } | ConvertTo-Json -Compress
  Add-Content -Path $logFile -Value $successLog
  Write-Host "[$finishedUtc] $canonicalJob completed successfully." -ForegroundColor Green

} catch {
  $failedUtc = [System.DateTime]::UtcNow.ToString("o")
  $errorMsg = $_.Exception.Message
  $failLog = @{
    timestamp_utc = $failedUtc
    job = $canonicalJob
    run_id = $RunId
    status = "FAILED"
    error = $errorMsg
  } | ConvertTo-Json -Compress
  Add-Content -Path $logFile -Value $failLog
  Write-Host "[$failedUtc] $canonicalJob FAILED: $errorMsg" -ForegroundColor Red
  exit 1
}
