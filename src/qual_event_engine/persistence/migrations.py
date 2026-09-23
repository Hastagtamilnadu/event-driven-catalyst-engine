from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Safe table-info helper — no f-string SQL; uses whitelist of known tables.
# §28 requires: "no SQL string formed from event content, source URLs,
# user review notes, or model output."
# PRAGMA table_info() cannot use parameter binding, so we whitelist names.
# ---------------------------------------------------------------------------
_KNOWN_TABLES = frozenset({
    "schema_migration", "job_run", "source_observation", "raw_document",
    "entity", "entity_alias", "entity_relationship", "canonical_event",
    "event_revision", "extracted_fact", "analyst_assessment",
    "review_decision", "paper_order", "paper_fill", "position_lot",
    "cash_ledger", "incident", "import_manifest",
    "price_bar", "source_health", "security_membership",
    "point_in_time_fundamental", "corporate_action", "blacklist",
})


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    if table not in _KNOWN_TABLES:
        raise ValueError(f"Unknown table: {table!r}")
    # PRAGMA table_info cannot use ? binding — table name is whitelisted above.
    rows = connection.execute(
        "SELECT name FROM pragma_table_info(?)", (table,)
    ).fetchall()
    return {str(r[0]) for r in rows}


def _tables_in_db(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def _record_migration(
    connection: sqlite3.Connection, version: str, sql: str
) -> None:
    """Record a migration in schema_migration if not already applied."""
    existing = connection.execute(
        "SELECT version FROM schema_migration WHERE version = ?", (version,)
    ).fetchone()
    if existing:
        return
    checksum = hashlib.sha256(sql.encode()).hexdigest()
    connection.execute(
        "INSERT INTO schema_migration(version, applied_at_utc, checksum_sha256)"
        " VALUES (?, ?, ?)",
        (version, datetime.now(UTC).isoformat(), checksum),
    )


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
    migration_version: str,
) -> None:
    cols = _column_names(connection, table)
    if column not in cols:
        sql = f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        connection.execute(sql)
        _record_migration(connection, migration_version, sql)


def apply_compatible_migrations(connection: sqlite3.Connection) -> None:
    """Additive migrations that bring an existing DB to §28 artifact compliance.

    Rules:
    - Only ADD COLUMN operations (SQLite cannot drop columns portably).
    - Never modify existing column definitions.
    - Never delete rows.
    - Every migration recorded in schema_migration with version + checksum.
    - Idempotent: safe to run on every startup.
    """
    from qual_event_engine.persistence.ddl import TABLES_SQL

    connection.executescript(TABLES_SQL)
    existing_tables = _tables_in_db(connection)

    # ------------------------------------------------------------------
    # v002 — source_observation: add §28 required columns
    # ------------------------------------------------------------------
    if "source_observation" in existing_tables:
        _add_column_if_missing(
            connection, "source_observation", "source_document_date",
            "TEXT", "v002_so_source_document_date"
        )
        _add_column_if_missing(
            connection, "source_observation", "http_status",
            "INTEGER", "v002_so_http_status"
        )
        _add_column_if_missing(
            connection, "source_observation", "timezone_original",
            "TEXT", "v002_so_timezone_original"
        )
        _add_column_if_missing(
            connection, "source_observation", "supersedes_observation_id",
            "TEXT REFERENCES source_observation(observation_id)",
            "v002_so_supersedes_observation_id"
        )
        _add_column_if_missing(
            connection, "source_observation", "system_first_seen_at_utc",
            "TEXT DEFAULT ''", "v002_so_system_first_seen_at_utc"
        )
        _add_column_if_missing(
            connection, "source_observation", "source_native_id",
            "TEXT DEFAULT ''", "v002_so_source_native_id"
        )
        _add_column_if_missing(
            connection, "source_observation", "source_url",
            "TEXT DEFAULT ''", "v002_so_source_url"
        )
        _add_column_if_missing(
            connection, "source_observation", "source_published_at_utc",
            "TEXT", "v002_so_source_published_at_utc"
        )
        _add_column_if_missing(
            connection, "source_observation", "downloaded_at_utc",
            "TEXT", "v002_so_downloaded_at_utc"
        )
        _add_column_if_missing(
            connection, "source_observation", "raw_sha256",
            "TEXT", "v002_so_raw_sha256"
        )
        _add_column_if_missing(
            connection, "source_observation", "retrieval_status",
            "TEXT DEFAULT 'SUCCESS'", "v002_so_retrieval_status"
        )
        _add_column_if_missing(
            connection, "source_observation", "parser_version",
            "TEXT DEFAULT '1'", "v002_so_parser_version"
        )
        _add_column_if_missing(
            connection, "source_observation", "job_run_id",
            "TEXT DEFAULT ''", "v002_so_job_run_id"
        )

    # ------------------------------------------------------------------
    # v003 — raw_document: add malware_scan_status
    # ------------------------------------------------------------------
    if "raw_document" in existing_tables:
        _add_column_if_missing(
            connection, "raw_document", "malware_scan_status",
            "TEXT NOT NULL DEFAULT 'NOT_SCANNED'",
            "v003_rd_malware_scan_status"
        )

    # ------------------------------------------------------------------
    # v004 — entity: add §28 required columns
    # ------------------------------------------------------------------
    if "entity" in existing_tables:
        _add_column_if_missing(
            connection, "entity", "isin",
            "TEXT", "v004_entity_isin"
        )
        _add_column_if_missing(
            connection, "entity", "entity_type",
            "TEXT NOT NULL DEFAULT 'LISTED_COMPANY'",
            "v004_entity_entity_type"
        )
        _add_column_if_missing(
            connection, "entity", "active_from",
            "TEXT", "v004_entity_active_from"
        )
        _add_column_if_missing(
            connection, "entity", "active_to",
            "TEXT", "v004_entity_active_to"
        )

    # ------------------------------------------------------------------
    # v005 — entity_alias: add §28 required columns
    # ------------------------------------------------------------------
    if "entity_alias" in existing_tables:
        _add_column_if_missing(
            connection, "entity_alias", "alias_normalized",
            "TEXT NOT NULL DEFAULT ''",
            "v005_ea_alias_normalized"
        )
        _add_column_if_missing(
            connection, "entity_alias", "alias_raw",
            "TEXT NOT NULL DEFAULT ''",
            "v005_ea_alias_raw"
        )
        _add_column_if_missing(
            connection, "entity_alias", "method",
            "TEXT NOT NULL DEFAULT 'LEGACY'",
            "v005_ea_method"
        )
        _add_column_if_missing(
            connection, "entity_alias", "approved_by",
            "TEXT", "v005_ea_approved_by"
        )
        _add_column_if_missing(
            connection, "entity_alias", "approved_at_utc",
            "TEXT", "v005_ea_approved_at_utc"
        )

    # ------------------------------------------------------------------
    # v006 — entity_relationship: add §28 required columns
    # ------------------------------------------------------------------
    if "entity_relationship" in existing_tables:
        _add_column_if_missing(
            connection, "entity_relationship", "related_entity_id",
            "TEXT REFERENCES entity(entity_id)",
            "v006_er_related_entity_id"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "relation_type",
            "TEXT NOT NULL DEFAULT 'UNKNOWN'",
            "v006_er_relation_type"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "effective_from",
            "TEXT", "v006_er_effective_from"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "effective_to",
            "TEXT", "v006_er_effective_to"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "evidence_observation_id",
            "TEXT REFERENCES source_observation(observation_id)",
            "v006_er_evidence_observation_id"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "confidence",
            "REAL NOT NULL DEFAULT 0.0",
            "v006_er_confidence"
        )
        _add_column_if_missing(
            connection, "entity_relationship", "review_status",
            "TEXT NOT NULL DEFAULT 'PENDING'",
            "v006_er_review_status"
        )

    # ------------------------------------------------------------------
    # v007 — canonical_event: add §28 required columns
    # ------------------------------------------------------------------
    if "canonical_event" in existing_tables:
        _add_column_if_missing(
            connection, "canonical_event", "entity_id",
            "TEXT REFERENCES entity(entity_id)",
            "v007_ce_entity_id"
        )
        _add_column_if_missing(
            connection, "canonical_event", "event_occurred_at_utc",
            "TEXT", "v007_ce_event_occurred_at_utc"
        )
        _add_column_if_missing(
            connection, "canonical_event", "decision_eligible_at_utc",
            "TEXT", "v007_ce_decision_eligible_at_utc"
        )
        _add_column_if_missing(
            connection, "canonical_event", "latest_revision_number",
            "INTEGER NOT NULL DEFAULT 1",
            "v007_ce_latest_revision_number"
        )
        _add_column_if_missing(
            connection, "canonical_event", "observation_id",
            "TEXT REFERENCES source_observation(observation_id)",
            "v007_ce_observation_id"
        )
        _add_column_if_missing(
            connection, "canonical_event", "legal_name",
            "TEXT", "v007_ce_legal_name"
        )
        _add_column_if_missing(
            connection, "canonical_event", "sector",
            "TEXT", "v007_ce_sector"
        )
        _add_column_if_missing(
            connection, "canonical_event", "firmness_level",
            "INTEGER", "v007_ce_firmness_level"
        )
        _add_column_if_missing(
            connection, "canonical_event", "event_value_inr",
            "REAL", "v007_ce_event_value_inr"
        )
        _add_column_if_missing(
            connection, "canonical_event", "ttm_revenue_inr",
            "REAL", "v007_ce_ttm_revenue_inr"
        )
        _add_column_if_missing(
            connection, "canonical_event", "materiality_ratio",
            "REAL", "v007_ce_materiality_ratio"
        )
        _add_column_if_missing(
            connection, "canonical_event", "headline",
            "TEXT", "v007_ce_headline"
        )
        _add_column_if_missing(
            connection, "canonical_event", "event_type",
            "TEXT NOT NULL DEFAULT 'UNKNOWN'", "v007_ce_event_type"
        )
        _add_column_if_missing(
            connection, "canonical_event", "event_status",
            "TEXT NOT NULL DEFAULT 'FINAL'", "v007_ce_event_status"
        )
        _add_column_if_missing(
            connection, "canonical_event", "entity_match_status",
            "TEXT NOT NULL DEFAULT 'UNVERIFIED'", "v007_ce_entity_match_status"
        )
        _add_column_if_missing(
            connection, "canonical_event", "event_state",
            "TEXT NOT NULL DEFAULT 'INGESTED'", "v007_ce_event_state"
        )
        _add_column_if_missing(
            connection, "canonical_event", "created_at_utc",
            "TEXT NOT NULL DEFAULT ''", "v007_ce_created_at_utc"
        )
        _add_column_if_missing(
            connection, "canonical_event", "symbol",
            "TEXT", "v007_ce_symbol"
        )
        _add_column_if_missing(
            connection, "canonical_event", "isin",
            "TEXT", "v007_ce_isin"
        )

    # ------------------------------------------------------------------
    # v008 — event_revision: add §28 required columns
    # ------------------------------------------------------------------
    if "event_revision" in existing_tables:
        _add_column_if_missing(
            connection, "event_revision", "event_revision_id",
            "TEXT", "v008_er_event_revision_id"
        )
        _add_column_if_missing(
            connection, "event_revision", "observation_id",
            "TEXT REFERENCES source_observation(observation_id)",
            "v008_er_observation_id"
        )
        _add_column_if_missing(
            connection, "event_revision", "revision_kind",
            "TEXT NOT NULL DEFAULT 'ORIGINAL'",
            "v008_er_revision_kind"
        )
        _add_column_if_missing(
            connection, "event_revision", "material_change_flag",
            "INTEGER NOT NULL DEFAULT 0 CHECK(material_change_flag IN (0,1))",
            "v008_er_material_change_flag"
        )
        _add_column_if_missing(
            connection, "event_revision", "superseded_at_utc",
            "TEXT", "v008_er_superseded_at_utc"
        )

    # ------------------------------------------------------------------
    # v009 — extracted_fact: add §28 required columns
    # ------------------------------------------------------------------
    if "extracted_fact" in existing_tables:
        _add_column_if_missing(
            connection, "extracted_fact", "event_revision_id",
            "TEXT REFERENCES event_revision(event_revision_id)",
            "v009_ef_event_revision_id"
        )
        _add_column_if_missing(
            connection, "extracted_fact", "value_normalized",
            "TEXT", "v009_ef_value_normalized"
        )
        _add_column_if_missing(
            connection, "extracted_fact", "event_id",
            "TEXT REFERENCES canonical_event(event_id)", "v009_ef_event_id"
        )

    # ------------------------------------------------------------------
    # v010 — analyst_assessment: add §28 required columns
    # ------------------------------------------------------------------
    if "analyst_assessment" in existing_tables:
        _add_column_if_missing(
            connection, "analyst_assessment", "event_revision_id",
            "TEXT REFERENCES event_revision(event_revision_id)",
            "v010_aa_event_revision_id"
        )
        _add_column_if_missing(
            connection, "analyst_assessment", "dossier_hash",
            "TEXT NOT NULL DEFAULT ''",
            "v010_aa_dossier_hash"
        )
        _add_column_if_missing(
            connection, "analyst_assessment", "event_id",
            "TEXT REFERENCES canonical_event(event_id)", "v010_aa_event_id"
        )
        _add_column_if_missing(
            connection, "analyst_assessment", "confidence",
            "TEXT DEFAULT 'HIGH'", "v010_aa_confidence"
        )

    # ------------------------------------------------------------------
    # v011 — review_decision: add assessment_id
    # ------------------------------------------------------------------
    if "review_decision" in existing_tables:
        _add_column_if_missing(
            connection, "review_decision", "assessment_id",
            "TEXT REFERENCES analyst_assessment(assessment_id)",
            "v011_rd_assessment_id"
        )

    # ------------------------------------------------------------------
    # v012 — paper_order: add participation_cap (exact §28 name)
    # ------------------------------------------------------------------
    if "paper_order" in existing_tables:
        _add_column_if_missing(
            connection, "paper_order", "participation_cap",
            "REAL NOT NULL DEFAULT 0.25",
            "v012_po_participation_cap"
        )
        _add_column_if_missing(
            connection, "paper_order", "participation_cap_pct",
            "REAL DEFAULT 0.25",
            "v012_po_participation_cap_pct"
        )
        _add_column_if_missing(
            connection, "paper_order", "quantity_remaining",
            "INTEGER DEFAULT 0",
            "v012_po_quantity_remaining"
        )

    # ------------------------------------------------------------------
    # v013 — position_lot: add stop_policy_version
    # ------------------------------------------------------------------
    if "position_lot" in existing_tables:
        _add_column_if_missing(
            connection, "position_lot", "stop_policy_version",
            "TEXT NOT NULL DEFAULT 'v1.0'",
            "v013_pl_stop_policy_version"
        )
        _add_column_if_missing(
            connection, "position_lot", "stop_price",
            "REAL",
            "v013_pl_stop_price"
        )
        _add_column_if_missing(
            connection, "position_lot", "event_id",
            "TEXT",
            "v013_pl_event_id"
        )

    # ------------------------------------------------------------------
    # v014 — import_manifest: create if absent
    # ------------------------------------------------------------------
    connection.execute("""
    CREATE TABLE IF NOT EXISTS import_manifest (
      import_id TEXT PRIMARY KEY,
      import_type TEXT NOT NULL,
      source_file TEXT NOT NULL,
      imported_at_utc TEXT NOT NULL,
      row_count INTEGER NOT NULL,
      checksum_sha256 TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','FAILED')),
      notes TEXT
    )
    """)
    _record_migration(connection, "v014_import_manifest", "CREATE TABLE IF NOT EXISTS import_manifest")

    # ------------------------------------------------------------------
    # v015 — legacy compatibility: exchange_first_seen_at_utc
    # ------------------------------------------------------------------
    if "source_observation" in existing_tables:
        _add_column_if_missing(
            connection, "source_observation", "exchange_first_seen_at_utc",
            "TEXT", "v015_so_exchange_first_seen_at_utc"
        )

    if "cash_ledger" in _tables_in_db(connection):
        _add_column_if_missing(
            connection, "cash_ledger", "strategy_id", "TEXT", "v017_cl_strategy_id"
        )
        _add_column_if_missing(
            connection, "cash_ledger", "occurred_at_utc", "TEXT DEFAULT ''", "v017_cl_occurred_at_utc"
        )
        _add_column_if_missing(
            connection, "cash_ledger", "entry_type", "TEXT DEFAULT 'INIT'", "v017_cl_entry_type"
        )
        _add_column_if_missing(
            connection, "cash_ledger", "reference_id", "TEXT DEFAULT ''", "v017_cl_reference_id"
        )
        _add_column_if_missing(
            connection, "cash_ledger", "amount_inr", "REAL DEFAULT 0.0", "v017_cl_amount_inr"
        )
        _add_column_if_missing(
            connection, "cash_ledger", "balance_after_inr", "REAL DEFAULT 0.0", "v017_cl_balance_after_inr"
        )

    # ------------------------------------------------------------------
    # v016 — import_manifest §30.1 required columns
    # ------------------------------------------------------------------
    if "import_manifest" in _tables_in_db(connection):
        _add_column_if_missing(
            connection, "import_manifest", "source_path", "TEXT", "v016_im_source_path"
        )
        _add_column_if_missing(
            connection, "import_manifest", "source_hash", "TEXT", "v016_im_source_hash"
        )
        _add_column_if_missing(
            connection, "import_manifest", "accepted_count", "INTEGER", "v016_im_accepted_count"
        )
        _add_column_if_missing(
            connection, "import_manifest", "rejected_count", "INTEGER", "v016_im_rejected_count"
        )
        _add_column_if_missing(
            connection, "import_manifest", "column_mapping_version", "TEXT", "v016_im_column_mapping_version"
        )
        _add_column_if_missing(
            connection, "import_manifest", "import_time", "TEXT", "v016_im_import_time"
        )
        _add_column_if_missing(
            connection, "import_manifest", "rejection_sample", "TEXT", "v016_im_rejection_sample"
        )

    # ------------------------------------------------------------------
    # v018 — price_bar §30.3 market-data contract fields
    # ------------------------------------------------------------------
    if "price_bar" in _tables_in_db(connection):
        _add_column_if_missing(connection, "price_bar", "market", "TEXT NOT NULL DEFAULT 'NSE'", "v018_pb_market")
        _add_column_if_missing(connection, "price_bar", "trade_count", "INTEGER", "v018_pb_trade_count")
        _add_column_if_missing(
            connection, "price_bar", "source_timestamp_utc", "TEXT", "v018_pb_source_timestamp_utc"
        )
        _add_column_if_missing(
            connection, "price_bar", "corporate_action_version", "TEXT", "v018_pb_corporate_action_version"
        )
        _add_column_if_missing(
            connection, "price_bar", "raw_or_adjusted", "TEXT NOT NULL DEFAULT 'RAW'", "v018_pb_raw_or_adjusted"
        )

    # ------------------------------------------------------------------
    # §28.2 Required indexes — idempotent (IF NOT EXISTS)
    # ------------------------------------------------------------------
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_observation_source_time"
        " ON source_observation(source_id, system_first_seen_at_utc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_isin_eligible"
        " ON canonical_event(isin, decision_eligible_at_utc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_fact_revision_field"
        " ON extracted_fact(event_revision_id, field_name)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_status_expiry"
        " ON paper_order(status, valid_until_utc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_fill_order_time"
        " ON paper_fill(paper_order_id, filled_at_utc)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_position_isin_status"
        " ON position_lot(isin, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_status_severity"
        " ON incident(status, severity)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fact_event_field"
        " ON extracted_fact(event_id, field_name)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_revision_event_revision_id"
        " ON event_revision(event_revision_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_assessment_event"
        " ON analyst_assessment(event_id)"
    )
    connection.commit()
