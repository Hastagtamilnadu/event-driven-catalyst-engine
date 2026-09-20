from __future__ import annotations

import sqlite3


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def apply_compatible_migrations(connection: sqlite3.Connection) -> None:
    """Additive migrations for databases created by an earlier engine build."""

    source_columns = _column_names(connection, "source_observation")
    if "exchange_first_seen_at_utc" not in source_columns:
        connection.execute(
            "ALTER TABLE source_observation ADD COLUMN exchange_first_seen_at_utc TEXT"
        )
    cash_columns = _column_names(connection, "cash_ledger")
    if "strategy_id" not in cash_columns:
        connection.execute(
            "ALTER TABLE cash_ledger ADD COLUMN strategy_id TEXT NOT NULL DEFAULT 'LEGACY'"
        )

    # Section 28 Tables Migration
    connection.execute("""
    CREATE TABLE IF NOT EXISTS entity (
      entity_id TEXT PRIMARY KEY,
      legal_name TEXT NOT NULL,
      cin TEXT,
      primary_isin TEXT,
      primary_symbol TEXT,
      sector TEXT,
      industry TEXT,
      status TEXT NOT NULL CHECK(status IN ('ACTIVE','SUSPENDED','DELISTED','MERGED')),
      created_at_utc TEXT NOT NULL,
      updated_at_utc TEXT NOT NULL
    );
    """)
    connection.execute("""
    CREATE TABLE IF NOT EXISTS entity_alias (
      alias_id TEXT PRIMARY KEY,
      entity_id TEXT NOT NULL REFERENCES entity(entity_id),
      alias_type TEXT NOT NULL CHECK(alias_type IN ('SYMBOL','ISIN','CIN','FORMER_NAME','TRADE_NAME','ABBREVIATION')),
      alias_value TEXT NOT NULL,
      source_id TEXT NOT NULL,
      valid_from_utc TEXT NOT NULL,
      valid_to_utc TEXT,
      confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
      UNIQUE(entity_id, alias_type, alias_value)
    );
    """)
    connection.execute("""
    CREATE TABLE IF NOT EXISTS entity_relationship (
      relationship_id TEXT PRIMARY KEY,
      parent_entity_id TEXT NOT NULL REFERENCES entity(entity_id),
      child_entity_id TEXT NOT NULL REFERENCES entity(entity_id),
      relationship_type TEXT NOT NULL CHECK(relationship_type IN ('SUBSIDIARY','JOINT_VENTURE','ASSOCIATE','PARENT','PROMOTER_GROUP')),
      ownership_pct REAL CHECK(ownership_pct >= 0 AND ownership_pct <= 100),
      effective_from_utc TEXT NOT NULL,
      effective_to_utc TEXT,
      source_id TEXT NOT NULL,
      UNIQUE(parent_entity_id, child_entity_id, relationship_type, effective_from_utc)
    );
    """)
    connection.execute("""
    CREATE TABLE IF NOT EXISTS event_revision (
      revision_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
      revision_number INTEGER NOT NULL CHECK(revision_number >= 1),
      revised_field TEXT NOT NULL,
      old_value_json TEXT,
      new_value_json TEXT NOT NULL,
      reason TEXT NOT NULL,
      revised_by TEXT NOT NULL,
      revised_at_utc TEXT NOT NULL,
      UNIQUE(event_id, revision_number, revised_field)
    );
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS ix_entity_symbol ON entity(primary_symbol);")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_entity_isin ON entity(primary_isin);")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_alias_value ON entity_alias(alias_value);")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_revision_event ON event_revision(event_id);")
