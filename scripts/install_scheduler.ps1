param([switch]$Enable)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run_job.ps1"

# Section 35.2: 6 Required Windows Scheduler Jobs
$tasks = @(
  @{ Name = "QualEngine_Nightly";      Time = "23:45"; Job = "QualEngine_Nightly";      Type = "Daily" },
  @{ Name = "QualEngine_Morning";      Time = "08:00"; Job = "QualEngine_Morning";      Type = "Daily" },
  @{ Name = "QualEngine_PreOpen";      Time = "08:50"; Job = "QualEngine_PreOpen";      Type = "Daily" },
  @{ Name = "QualEngine_Intraday";     Time = "09:15"; Job = "QualEngine_Intraday";     Type = "Daily" },
  @{ Name = "QualEngine_Close";        Time = "15:45"; Job = "QualEngine_Close";        Type = "Daily" },
  @{ Name = "QualEngine_MonthlyAudit"; Time = "00:00"; Job = "QualEngine_MonthlyAudit"; Type = "Monthly" }
)

Write-Host "Registering 6 Windows Task Scheduler jobs per Section 35.2..."

foreach ($task in $tasks) {
  $taskCommand = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Job $($task.Job)"
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskCommand
  if ($task.Type -eq "Daily") {
    $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
  } else {
    $trigger = New-ScheduledTaskTrigger -Daily -At $task.Time
  }

  try {
    $registered = Register-ScheduledTask -TaskName $task.Name -Action $action -Trigger $trigger -Force
    if (-not $Enable) {
      Disable-ScheduledTask -TaskName $task.Name | Out-Null
      Write-Host "  -> Created task: $($task.Name) (DISABLED by default)"
    } else {
      Write-Host "  -> Created task: $($task.Name) (ENABLED)"
    }
  } catch {
    Write-Warning "Could not register task $($task.Name): $_."
  }
}

Write-Host "Scheduler installation complete. Tasks are disabled by default until smoke test passes."
