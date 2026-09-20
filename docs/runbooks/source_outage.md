# Runbook: Source Outage (RB-01)

## 1. Detection
- Health check job fails for a specific source adapter (`source_health` table status='DEGRADED' or 'FAILED').
- Document count drops below expected daily/weekly bounds specified in `configs/sources.yaml`.
- Consecutive HTTP 5xx or connection timeout errors exceed threshold (3 consecutive attempts).

## 2. Immediate Freeze Action
- Set source status to `FROZEN` in `source_health` table.
- Freeze all strategy instances that depend primarily on the affected source (e.g. CR-01 for ratings outage).
- Halt automated paper order generation for the affected source.
- Do NOT alter existing open paper positions unless an explicit stop is triggered by market bars.

## 3. Diagnosis
1. Check upstream network connectivity and TLS endpoint status using `curl` or `Test-NetConnection`.
2. Inspect `data/logs/YYYY/MM/DD/health.log` for specific HTTP response codes or parser exceptions.
3. Verify if source URL schema or authentication/access contract changed.
4. Check if upstream portal is under maintenance or rate-limiting.

## 4. Recovery
1. If transient outage, wait for exponential backoff window (15m, 30m, 60m).
2. If schema change, update adapter parser version and test with recorded fixture.
3. Trigger ad-hoc source poll: `uv run qual-engine ingest --source <source_id>`.
4. Verify HTTP 200 and successful document SHA-256 archiving.

## 5. Reconciliation
1. Identify missing publication window: `SELECT max(source_published_at_utc) FROM source_observation WHERE source_id=?`.
2. Re-poll missing time range using cursor backtrack.
3. Ensure no duplicate events created using payload hash idempotency.

## 6. Closure Evidence
- Source health record updated to `OK` with `error_summary=NULL`.
- Verified row count of backfilled observations in `source_observation`.
- Incident marked `RESOLVED` in `incident` table with timestamp and operator notes.

## 7. Prevention Action
- Review upstream availability SLA.
- Adjust timeout and retry parameters in `configs/sources.yaml` if network latency shifted.
