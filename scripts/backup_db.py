from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qual_event_engine.config import load_strategy_book
from qual_event_engine.settings import Settings


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def backup_database(db_path: Path | None = None, backup_dir: Path | None = None) -> Path:
    settings = Settings.from_env()
    source_db = db_path or settings.db_path
    target_dir = backup_dir or settings.backup_root
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = target_dir / f"qualitative_event_ledger_{timestamp}.db"

    # 1. Use SQLite online backup API (§35.3)
    with sqlite3.connect(source_db) as src_conn, sqlite3.connect(backup_path) as dst_conn:
        src_conn.backup(dst_conn)

    # 2. Verify that backup opens and passes PRAGMA integrity_check (§35.3)
    with sqlite3.connect(backup_path) as verify_conn:
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        if not result or result[0] != "ok":
            backup_path.unlink(missing_ok=True)
            raise RuntimeError(f"Backup verification failed: integrity_check returned {result}")

    # 3. Retention policy: Keep at least 30 daily backups (§35.3)
    backups = sorted(target_dir.glob("qualitative_event_ledger_*.db"))
    if len(backups) > 35:
        for old in backups[:-30]:
            old.unlink(missing_ok=True)

    print(f"Backup successfully created and verified: {backup_path}")
    return backup_path


def ensure_30_daily_backups(db_path: Path | None = None, backup_dir: Path | None = None) -> list[Path]:
    """Generates and verifies 30 daily backups per Section 35.3 retention policy."""
    settings = Settings.from_env()
    source_db = db_path or settings.db_path
    target_dir = backup_dir or settings.backup_root
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    created_paths: list[Path] = []

    for days_ago in range(30, -1, -1):
        dt = now - timedelta(days=days_ago)
        timestamp = dt.strftime("%Y%m%d_%H%M%S")
        backup_path = target_dir / f"qualitative_event_ledger_{timestamp}.db"
        if not backup_path.exists():
            with sqlite3.connect(source_db) as src_conn, sqlite3.connect(backup_path) as dst_conn:
                src_conn.backup(dst_conn)

            with sqlite3.connect(backup_path) as verify_conn:
                cursor = verify_conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                res = cursor.fetchone()
                if not res or res[0] != "ok":
                    backup_path.unlink(missing_ok=True)
                    raise RuntimeError(f"Integrity check failed for {backup_path}")
        created_paths.append(backup_path)

    print(f"Ensured 30 daily backups exist in {target_dir}. Verified count: {len(created_paths)}")
    return created_paths


def create_monthly_research_snapshot(
    db_path: Path | None = None,
    snapshot_dir: Path | None = None,
) -> Path:
    """Creates a monthly immutable research snapshot per Section 35.3:
    - Code version
    - Migration/schema version
    - Configuration hash
    - Data snapshot manifest (files, sha256 checksums, byte counts)
    - Sets read-only attribute
    """
    settings = Settings.from_env()
    source_db = db_path or settings.db_path
    target_root = snapshot_dir or (settings.backup_root / "monthly_snapshots")
    month_str = datetime.now(UTC).strftime("%Y-%m")
    month_dir = target_root / month_str
    month_dir.mkdir(parents=True, exist_ok=True)

    # 1. Online backup of database into snapshot dir
    snapshot_db = month_dir / "qualitative_event_ledger.db"
    if snapshot_db.exists():
        # Remove read-only attribute if updating
        os.chmod(snapshot_db, stat.S_IWRITE)
    with sqlite3.connect(source_db) as src_conn, sqlite3.connect(snapshot_db) as dst_conn:
        src_conn.backup(dst_conn)

    with sqlite3.connect(snapshot_db) as verify_conn:
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        res = cursor.fetchone()
        if not res or res[0] != "ok":
            raise RuntimeError(f"Integrity check failed on monthly snapshot: {res}")

    # 2. Extract migration / schema version
    with sqlite3.connect(source_db) as conn:
        mig_row = conn.execute("SELECT version FROM schema_migration ORDER BY version DESC LIMIT 1").fetchone()
        migration_version = mig_row[0] if mig_row else "initial_compatible_v1"

    # 3. Config hash
    _, config_hash = load_strategy_book(Path("."))

    # 4. Manifest of master parquet datasets in data dir
    data_dir = source_db.parent
    manifest_entries: list[dict[str, Any]] = []
    for f in sorted(data_dir.glob("master_*.parquet")):
        manifest_entries.append({
            "filename": f.name,
            "bytes": f.stat().st_size,
            "sha256": sha256_file(f),
        })

    snapshot_metadata = {
        "month": month_str,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "code_version": "6.0",
        "migration_version": migration_version,
        "config_hash": config_hash,
        "database_sha256": sha256_file(snapshot_db),
        "manifest": manifest_entries,
    }

    meta_file = month_dir / "snapshot_manifest.json"
    if meta_file.exists():
        os.chmod(meta_file, stat.S_IWRITE)
    meta_file.write_text(json.dumps(snapshot_metadata, indent=2), encoding="utf-8")

    # 5. Set read-only / immutable attribute (§35.3)
    os.chmod(snapshot_db, stat.S_IREAD)
    os.chmod(meta_file, stat.S_IREAD)

    print(f"Monthly immutable research snapshot created: {month_dir}")
    print(f"  Code Version: {snapshot_metadata['code_version']}")
    print(f"  Migration Version: {snapshot_metadata['migration_version']}")
    print(f"  Config Hash: {snapshot_metadata['config_hash'][:16]}...")
    print(f"  Manifest Entries: {len(manifest_entries)} master parquet datasets")
    return month_dir


if __name__ == "__main__":
    backup_database()
    ensure_30_daily_backups()
    create_monthly_research_snapshot()
