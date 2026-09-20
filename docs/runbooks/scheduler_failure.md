# Runbook: Scheduler Failure (RB-07)

## 1. Detection
- Scheduled task does not start at scheduled time (e.g. 08:00 IST for `QualEngine_Morning`).
- Task runs but terminates with non-zero exit code (`$LASTEXITCODE -ne 0`).
- Heartbeat timestamp in `source_health` or `job_run` is older than expected execution window.
- Windows Task Scheduler reports task status `Failed` (0x1 or other non-zero code).

## 2. Immediate Freeze Action
- Verify if any in-flight order processing was interrupted.
- If pre-market order intent creation failed (`QualEngine_PreOpen`), block market open fill processing until reviewed.
- Prevent duplicate overlapping task execution by ensuring process mutex/lock file.

## 3. Diagnosis
1. Inspect Task Scheduler history in Windows Event Viewer: `Applications and Services Logs -> Microsoft -> Windows -> TaskScheduler -> Operational`.
2. Inspect dated job log file in `data/logs/YYYY/MM/DD/<job_name>.log`.
3. Check PowerShell execution policy and user account permissions.
4. Verify environment variables and Python executable path in `.venv`.

## 4. Recovery
1. If crash due to temporary resource contention, manually trigger the job:
   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_job.ps1 -Job <job_name>
   ```
2. Verify job completes with exit code 0.
3. Check `job_run` table for `status='SUCCEEDED'`.

## 5. Reconciliation
1. Verify no duplicate events or orders were created during restart.
2. Confirm state transitions in `canonical_event` and `paper_order` match expected phase progress.

## 6. Closure Evidence
- Job run recorded as `SUCCEEDED` in `job_run` table.
- Log file shows clean completion without stack traces.
- Incident report closed with resolution details.

## 7. Prevention Action
- Configure Task Scheduler retry settings: restart on failure up to 2 times with 5-minute interval.
- Set up automated alerting if heartbeat is absent 15 minutes after scheduled job start.
