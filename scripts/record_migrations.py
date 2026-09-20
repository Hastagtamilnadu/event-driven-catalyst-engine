from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DATA_ROOT = Path("D:/02_Trading/data")
DB_PATH = DATA_ROOT / "qualitative_event_ledger.db"
MIGRATIONS_DIR = Path("D:/02_Trading/qual_event_engine/migrations")

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = ON")

migration_files = [
    ("001_initial_schema", MIGRATIONS_DIR / "001_initial_schema.sql"),
    ("002_views_and_indexes", MIGRATIONS_DIR / "002_views_and_indexes.sql"),
    ("003_drop_forward_returns", MIGRATIONS_DIR / "003_drop_forward_returns.sql"),
]

now_utc = datetime.now(UTC).isoformat()

for version, path in migration_files:
    if not path.exists():
        raise FileNotFoundError(f"Migration file missing: {path}")
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()

    conn.execute(
        """
        INSERT INTO schema_migration (version, applied_at_utc, checksum_sha256)
        VALUES (?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            applied_at_utc = excluded.applied_at_utc,
            checksum_sha256 = excluded.checksum_sha256
        """,
        (version, now_utc, checksum),
    )
    print(f"Recorded migration {version}: checksum={checksum[:16]}...")

conn.commit()

rows = conn.execute("SELECT version, applied_at_utc, checksum_sha256 FROM schema_migration ORDER BY version").fetchall()
print("Current schema_migration table:")
for r in rows:
    print(r)

conn.close()
