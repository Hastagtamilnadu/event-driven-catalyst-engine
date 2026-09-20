# Runbook: Database Recovery (RB-04)

## 1. Detection
- SQLite returns `sqlite3.DatabaseError`, `disk I/O error`, or `database disk image is malformed`.
- `PRAGMA integrity_check;` returns any value other than `ok`.
- Database lock timeout occurs repeatedly (`busy_timeout = 5000` exceeded).
- WAL file grows uncontrollably without checkpointing.

## 2. Immediate Freeze Action
- Immediately terminate all running engine processes and Task Scheduler jobs.
- Take a point-in-time binary copy of `qualitative_event_ledger.db` and associated `-wal` and `-shm` files to `data/quarantine/`.
- Set platform operational state to `DATABASE_EMERGENCY_FREEZE`.

## 3. Diagnosis
1. Run `PRAGMA integrity_check;` on the live database.
2. Check disk space and file permissions on `D:\02_Trading\data\`.
3. Check Windows Event Viewer for disk errors or hard shutdown events.
4. Inspect latest verified backup in `data/backups/`.

## 4. Recovery
1. Attempt SQLite recovery:
   ```bash
   sqlite3 corrupted.db ".recover" | sqlite3 recovered.db
   ```
2. If recovery fails or reports loss, restore from the latest verified daily backup in `data/backups/YYYY/MM/DD/qualitative_event_ledger_backup.db`.
3. Re-open restored database and execute:
   ```sql
   PRAGMA foreign_keys = ON;
   PRAGMA integrity_check;
   ```
4. Re-apply any WAL transactions or re-play event journals from raw archive.

## 5. Reconciliation
1. Compare table counts between backup manifest and restored database.
2. Verify all `paper_fill`, `position_lot`, and `cash_ledger` balances tie out.
3. Re-run `uv run qual-engine report --report performance` to verify state integrity.

## 6. Closure Evidence
- `PRAGMA integrity_check;` returns `ok`.
- All foreign key relationships verified with zero dangling references.
- Incident resolution report documented in `incident` table.

## 7. Prevention Action
- Enforce daily automated SQLite backup API routine with automatic reopen and integrity check.
- Retain minimum 30 daily backups and monthly immutable snapshots.
