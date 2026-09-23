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

$venvActivate = Join-Path $projectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
  . $venvActivate
}

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

$stdoutLog = Join-Path $dateFolder "$canonicalJob.$RunId.stdout.log"
$stderrLog = Join-Path $dateFolder "$canonicalJob.$RunId.stderr.log"

function Invoke-LoggedJob {
  param([string[]]$Command)
  Write-Host ("  -> " + ($Command -join " "))
  $stdout = & $Command[0] $Command[1..($Command.Length - 1)] 2>> $stderrLog
  if ($null -ne $stdout) {
    $stdout | Tee-Object -FilePath $stdoutLog -Append
  }
  if ($LASTEXITCODE -ne 0) {
    throw ("Command failed with exit code " + $LASTEXITCODE + ": " + ($Command -join " "))
  }
}

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
      Invoke-LoggedJob @("uv", "run", "qual-engine", "ingest", "--source", "exchange", "--mode", "LIVE_POLL")
      Invoke-LoggedJob @("uv", "run", "python", "scripts/run_adapter_health_checks.py")
      Invoke-LoggedJob @("uv", "run", "qual-engine", "process-events")
    }
    "QualEngine_Morning" {
      Invoke-LoggedJob @("uv", "run", "qual-engine", "health")
    }
    "QualEngine_PreOpen" {
      Invoke-LoggedJob @("uv", "run", "qual-engine", "create-paper-intents")
    }
    "QualEngine_Intraday" {
      Invoke-LoggedJob @("uv", "run", "qual-engine", "ingest", "--source", "exchange", "--mode", "LIVE_POLL")
      Invoke-LoggedJob @("uv", "run", "qual-engine", "run-paper")
    }
    "QualEngine_Close" {
      Invoke-LoggedJob @("uv", "run", "qual-engine", "run-paper")
      Invoke-LoggedJob @("uv", "run", "qual-engine", "report", "--report", "performance")
      Invoke-LoggedJob @("uv", "run", "python", "scripts/backup_db.py")
    }
    "QualEngine_MonthlyAudit" {
      Invoke-LoggedJob @("uv", "run", "pytest", "tests/unit/test_benchmarks.py", "-q")
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
