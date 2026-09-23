from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical DDL — Version 6.0 artifact §28.1
# Exact column names as specified. No deviation.
# ---------------------------------------------------------------------------

TABLES_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_migration (
  version TEXT PRIMARY KEY,
  applied_at_utc TEXT NOT NULL,
  checksum_sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_run (
  job_run_id TEXT PRIMARY KEY,
  job_name TEXT NOT NULL,
  started_at_utc TEXT NOT NULL,
  finished_at_utc TEXT,
  status TEXT NOT NULL CHECK(status IN ('STARTED','SUCCEEDED','FAILED','BLOCKED')),
  config_hash TEXT NOT NULL,
  code_version TEXT NOT NULL,
  error_summary TEXT
);

CREATE TABLE IF NOT EXISTS source_observation (
  observation_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  source_native_id TEXT,
  source_url TEXT NOT NULL,
  source_published_at_utc TEXT,
  source_document_date TEXT,
  system_first_seen_at_utc TEXT NOT NULL,
  downloaded_at_utc TEXT,
  exchange_first_seen_at_utc TEXT,
  raw_sha256 TEXT,
  retrieval_status TEXT NOT NULL,
  http_status INTEGER,
  parser_version TEXT,
  timezone_original TEXT,
  supersedes_observation_id TEXT REFERENCES source_observation(observation_id),
  job_run_id TEXT NOT NULL REFERENCES job_run(job_run_id),
  UNIQUE(source_id, source_native_id, raw_sha256)
);

CREATE TABLE IF NOT EXISTS raw_document (
  raw_sha256 TEXT PRIMARY KEY,
  local_path TEXT NOT NULL UNIQUE,
  mime_type TEXT,
  bytes INTEGER NOT NULL CHECK(bytes >= 0),
  page_count INTEGER,
  extracted_characters INTEGER,
  extraction_quality TEXT NOT NULL,
  archived_at_utc TEXT NOT NULL,
  malware_scan_status TEXT NOT NULL DEFAULT 'NOT_SCANNED',
  parser_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity (
  entity_id TEXT PRIMARY KEY,
  isin TEXT UNIQUE,
  cin TEXT,
  legal_name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  active_from TEXT,
  active_to TEXT
);

CREATE TABLE IF NOT EXISTS entity_alias (
  alias_id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entity(entity_id),
  alias_normalized TEXT NOT NULL,
  alias_raw TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  method TEXT NOT NULL,
  approved_by TEXT,
  approved_at_utc TEXT,
  UNIQUE(entity_id, alias_normalized)
);

CREATE TABLE IF NOT EXISTS entity_relationship (
  relationship_id TEXT PRIMARY KEY,
  parent_entity_id TEXT NOT NULL REFERENCES entity(entity_id),
  related_entity_id TEXT NOT NULL REFERENCES entity(entity_id),
  relation_type TEXT NOT NULL,
  ownership_pct REAL,
  effective_from TEXT,
  effective_to TEXT,
  evidence_observation_id TEXT REFERENCES source_observation(observation_id),
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  review_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_event (
  event_id TEXT PRIMARY KEY,
  entity_id TEXT REFERENCES entity(entity_id),
  isin TEXT,
  symbol TEXT,
  event_type TEXT NOT NULL,
  event_status TEXT NOT NULL,
  event_occurred_at_utc TEXT,
  decision_eligible_at_utc TEXT,
  entity_match_status TEXT NOT NULL,
  event_state TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  latest_revision_number INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS event_revision (
  event_revision_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  observation_id TEXT NOT NULL REFERENCES source_observation(observation_id),
  revision_number INTEGER NOT NULL,
  revision_kind TEXT NOT NULL,
  material_change_flag INTEGER NOT NULL CHECK(material_change_flag IN (0,1)),
  superseded_at_utc TEXT,
  UNIQUE(event_id, revision_number),
  UNIQUE(event_id, observation_id)
);

CREATE TABLE IF NOT EXISTS extracted_fact (
  fact_id TEXT PRIMARY KEY,
  event_revision_id TEXT NOT NULL REFERENCES event_revision(event_revision_id),
  field_name TEXT NOT NULL,
  value_json TEXT,
  value_normalized TEXT,
  page_number INTEGER,
  evidence_text TEXT NOT NULL,
  extractor_name TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  validation_status TEXT NOT NULL,
  UNIQUE(event_revision_id, field_name)
);

CREATE TABLE IF NOT EXISTS analyst_assessment (
  assessment_id TEXT PRIMARY KEY,
  event_revision_id TEXT NOT NULL REFERENCES event_revision(event_revision_id),
  dossier_hash TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  rationale TEXT NOT NULL,
  invalidating_fact TEXT NOT NULL,
  schema_valid INTEGER NOT NULL CHECK(schema_valid IN (0,1)),
  semantic_valid INTEGER NOT NULL CHECK(semantic_valid IN (0,1)),
  latency_ms INTEGER,
  created_at_utc TEXT NOT NULL,
  UNIQUE(event_revision_id, model_id, prompt_version, input_hash)
);

CREATE TABLE IF NOT EXISTS review_decision (
  review_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  assessment_id TEXT REFERENCES analyst_assessment(assessment_id),
  reviewer TEXT NOT NULL,
  decision TEXT NOT NULL,
  rationale TEXT NOT NULL,
  reviewed_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_order (
  paper_order_id TEXT PRIMARY KEY,
  client_order_id TEXT NOT NULL UNIQUE,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  isin TEXT,
  side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
  quantity_requested INTEGER NOT NULL CHECK(quantity_requested > 0),
  order_type TEXT NOT NULL,
  limit_price REAL,
  trigger_price REAL,
  participation_cap REAL NOT NULL DEFAULT 0.25,
  valid_from_utc TEXT NOT NULL,
  valid_until_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  decision_snapshot_hash TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_fill (
  paper_fill_id TEXT PRIMARY KEY,
  paper_order_id TEXT NOT NULL REFERENCES paper_order(paper_order_id),
  filled_at_utc TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  raw_price REAL NOT NULL,
  spread_cost_inr REAL NOT NULL,
  impact_cost_inr REAL NOT NULL,
  statutory_cost_inr REAL NOT NULL,
  final_price REAL NOT NULL,
  fill_reason TEXT NOT NULL,
  market_data_ref TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_lot (
  position_lot_id TEXT PRIMARY KEY,
  isin TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  opened_by_fill_id TEXT NOT NULL REFERENCES paper_fill(paper_fill_id),
  opened_at_utc TEXT NOT NULL,
  quantity_open INTEGER NOT NULL CHECK(quantity_open >= 0),
  average_cost REAL NOT NULL,
  stop_policy_version TEXT NOT NULL DEFAULT 'v1.0',
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cash_ledger (
  cash_entry_id TEXT PRIMARY KEY,
  occurred_at_utc TEXT NOT NULL,
  entry_type TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  amount_inr REAL NOT NULL,
  balance_after_inr REAL NOT NULL,
  UNIQUE(entry_type, reference_id)
);

CREATE TABLE IF NOT EXISTS incident (
  incident_id TEXT PRIMARY KEY,
  severity TEXT NOT NULL,
  service TEXT NOT NULL,
  opened_at_utc TEXT NOT NULL,
  closed_at_utc TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  resolution TEXT
);

-- ---------------------------------------------------------------------------
-- Extended tables not in §28 core DDL but required for production operation
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS import_manifest (
  import_id TEXT PRIMARY KEY,
  import_type TEXT NOT NULL,
  source_file TEXT NOT NULL,
  imported_at_utc TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  checksum_sha256 TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('COMPLETE','PARTIAL','FAILED')),
  notes TEXT,
  source_path TEXT NOT NULL DEFAULT '',
  source_hash TEXT NOT NULL DEFAULT '',
  accepted_count INTEGER NOT NULL DEFAULT 0,
  rejected_count INTEGER NOT NULL DEFAULT 0,
  column_mapping_version TEXT NOT NULL DEFAULT '',
  import_time TEXT NOT NULL DEFAULT '',
  rejection_sample TEXT
);

CREATE TABLE IF NOT EXISTS price_bar (
  bar_id TEXT PRIMARY KEY,
  market TEXT NOT NULL DEFAULT 'NSE',
  isin TEXT,
  symbol TEXT NOT NULL,
  interval TEXT NOT NULL,
  open_time_utc TEXT NOT NULL,
  close_time_utc TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume_shares REAL NOT NULL,
  turnover_inr REAL NOT NULL,
  trade_count INTEGER,
  is_complete INTEGER NOT NULL CHECK(is_complete IN (0,1)),
  source_id TEXT NOT NULL,
  source_timestamp_utc TEXT,
  corporate_action_version TEXT,
  raw_or_adjusted TEXT NOT NULL DEFAULT 'RAW',
  UNIQUE(symbol, interval, open_time_utc, source_id)
);

CREATE TABLE IF NOT EXISTS source_health (
  health_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  checked_at_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  document_count INTEGER NOT NULL,
  detail TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_membership (
  membership_id TEXT PRIMARY KEY,
  isin TEXT,
  symbol TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  effective_from_utc TEXT NOT NULL,
  effective_to_utc TEXT,
  series TEXT NOT NULL,
  listed_status TEXT NOT NULL,
  surveillance_status TEXT NOT NULL,
  price_band_pct REAL,
  market_cap_inr REAL,
  adv20_shares REAL,
  adt20_inr REAL,
  eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
  eligibility_reasons TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_version TEXT NOT NULL,
  UNIQUE(symbol, effective_from_utc, source_version)
);

CREATE TABLE IF NOT EXISTS point_in_time_fundamental (
  fundamental_id TEXT PRIMARY KEY,
  isin TEXT,
  symbol TEXT NOT NULL,
  metric TEXT NOT NULL,
  value REAL NOT NULL,
  period_end TEXT,
  issuer_disseminated_at_utc TEXT,
  system_first_seen_at_utc TEXT NOT NULL,
  eligible_at_utc TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_version TEXT NOT NULL,
  supersedes_fundamental_id TEXT,
  UNIQUE(symbol, metric, eligible_at_utc, source_version)
);

CREATE TABLE IF NOT EXISTS corporate_action (
  action_id TEXT PRIMARY KEY,
  isin TEXT,
  symbol TEXT NOT NULL,
  action_type TEXT NOT NULL,
  ex_date TEXT NOT NULL,
  adjustment_factor REAL NOT NULL,
  source_id TEXT NOT NULL,
  source_document_ref TEXT,
  UNIQUE(symbol, action_type, ex_date, source_id)
);

CREATE TABLE IF NOT EXISTS blacklist (
  blacklist_id TEXT PRIMARY KEY,
  isin TEXT,
  symbol TEXT NOT NULL,
  reason_event_id TEXT REFERENCES canonical_event(event_id),
  starts_at_utc TEXT NOT NULL,
  ends_at_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  UNIQUE(symbol, reason_event_id)
);

"""

INDEXES_SQL = """
-- ---------------------------------------------------------------------------
-- §28.2 Required indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_observation_source_time
  ON source_observation(source_id, system_first_seen_at_utc);
CREATE INDEX IF NOT EXISTS ix_event_isin_eligible
  ON canonical_event(isin, decision_eligible_at_utc);
CREATE INDEX IF NOT EXISTS ix_fact_revision_field
  ON extracted_fact(event_revision_id, field_name);
CREATE INDEX IF NOT EXISTS ix_order_status_expiry
  ON paper_order(status, valid_until_utc);
CREATE INDEX IF NOT EXISTS ix_fill_order_time
  ON paper_fill(paper_order_id, filled_at_utc);
CREATE INDEX IF NOT EXISTS ix_position_isin_status
  ON position_lot(isin, status);
CREATE INDEX IF NOT EXISTS ix_incident_status_severity
  ON incident(status, severity);
"""

SCHEMA_SQL = TABLES_SQL + "\n" + INDEXES_SQL

