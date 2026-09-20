import sqlite3
from pathlib import Path

from qual_event_engine.persistence.database import connect, initialise
from qual_event_engine.persistence.migrations import apply_compatible_migrations


def test_database_initialisation_and_repeatable_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "migration_test.db"

    # Step 1: Initialise fresh database
    initialise(db_path)
    with connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        cursor.execute("PRAGMA foreign_keys")
        assert cursor.fetchone()[0] == 1

        # Check table count (23 tables)
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        count_1 = cursor.fetchone()[0]
        assert count_1 == 23

    # Step 2: Re-run initialise to prove idempotency
    initialise(db_path)
    with connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        count_2 = cursor.fetchone()[0]
        assert count_2 == count_1

    # Step 3: Run apply_compatible_migrations multiple times directly
    with connect(db_path) as conn:
        apply_compatible_migrations(conn)
        apply_compatible_migrations(conn)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        assert cursor.fetchone()[0] == "ok"


def test_schema_from_legacy_to_migrated(tmp_path: Path) -> None:
    # Simulate a bare database with minimal schema missing new columns/tables
    db_path = tmp_path / "legacy_test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE source_observation (observation_id TEXT PRIMARY KEY, source_id TEXT)")
    conn.execute("CREATE TABLE cash_ledger (cash_entry_id TEXT PRIMARY KEY, amount_inr REAL)")
    conn.execute("CREATE TABLE canonical_event (event_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    # Apply migrations
    with connect(db_path) as conn:
        apply_compatible_migrations(conn)
        # Verify columns added
        obs_cols = {row[1] for row in conn.execute("PRAGMA table_info(source_observation)").fetchall()}
        assert "exchange_first_seen_at_utc" in obs_cols
        cash_cols = {row[1] for row in conn.execute("PRAGMA table_info(cash_ledger)").fetchall()}
        assert "strategy_id" in cash_cols

        # Verify new tables created
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "entity" in tables
        assert "entity_alias" in tables
        assert "entity_relationship" in tables
        assert "event_revision" in tables
