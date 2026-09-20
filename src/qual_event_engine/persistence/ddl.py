from __future__ import annotations

SCHEMA_SQL = """
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
  source_native_id TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_published_at_utc TEXT NOT NULL,
  exchange_first_seen_at_utc TEXT,
  system_first_seen_at_utc TEXT NOT NULL,
  downloaded_at_utc TEXT NOT NULL,
  raw_sha256 TEXT NOT NULL,
  retrieval_status TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  job_run_id TEXT NOT NULL REFERENCES job_run(job_run_id),
  UNIQUE(source_id, source_native_id, raw_sha256)
);
CREATE TABLE IF NOT EXISTS raw_document (
  raw_sha256 TEXT PRIMARY KEY,
  local_path TEXT NOT NULL UNIQUE,
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes >= 0),
  page_count INTEGER,
  extracted_characters INTEGER NOT NULL,
  extraction_quality TEXT NOT NULL,
  archived_at_utc TEXT NOT NULL,
  parser_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canonical_event (
  event_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL UNIQUE REFERENCES source_observation(observation_id),
  isin TEXT,
  symbol TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  sector TEXT,
  event_type TEXT NOT NULL,
  event_status TEXT NOT NULL,
  firmness_level INTEGER NOT NULL CHECK(firmness_level BETWEEN 0 AND 5),
  event_value_inr REAL,
  ttm_revenue_inr REAL,
  materiality_ratio REAL,
  entity_match_status TEXT NOT NULL,
  event_state TEXT NOT NULL,
  headline TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extracted_fact (
  fact_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  field_name TEXT NOT NULL,
  value_json TEXT,
  evidence_text TEXT NOT NULL,
  page_number INTEGER,
  extractor_name TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  validation_status TEXT NOT NULL,
  UNIQUE(event_id, field_name)
);
CREATE TABLE IF NOT EXISTS analyst_assessment (
  assessment_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE REFERENCES canonical_event(event_id),
  model_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  rationale TEXT NOT NULL,
  invalidating_fact TEXT NOT NULL,
  confidence TEXT NOT NULL,
  schema_valid INTEGER NOT NULL CHECK(schema_valid IN (0,1)),
  semantic_valid INTEGER NOT NULL CHECK(semantic_valid IN (0,1)),
  latency_ms INTEGER,
  created_at_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_decision (
  review_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  reviewer TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('APPROVE','REJECT','REQUEST_MORE_EVIDENCE','OVERRIDE_TO_WATCH')),
  rationale TEXT NOT NULL,
  reviewed_at_utc TEXT NOT NULL,
  UNIQUE(event_id, reviewer, reviewed_at_utc)
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
  quantity_remaining INTEGER NOT NULL CHECK(quantity_remaining >= 0),
  order_type TEXT NOT NULL,
  limit_price REAL,
  trigger_price REAL,
  participation_cap_pct REAL NOT NULL CHECK(participation_cap_pct > 0),
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
  isin TEXT,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  event_id TEXT NOT NULL REFERENCES canonical_event(event_id),
  opened_by_fill_id TEXT NOT NULL REFERENCES paper_fill(paper_fill_id),
  opened_at_utc TEXT NOT NULL,
  quantity_open INTEGER NOT NULL CHECK(quantity_open >= 0),
  average_cost REAL NOT NULL,
  stop_price REAL NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_ledger (
  cash_entry_id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  occurred_at_utc TEXT NOT NULL,
  entry_type TEXT NOT NULL,
  reference_id TEXT NOT NULL,
  amount_inr REAL NOT NULL,
  balance_after_inr REAL NOT NULL,
  UNIQUE(strategy_id, entry_type, reference_id)
);
CREATE TABLE IF NOT EXISTS price_bar (
  bar_id TEXT PRIMARY KEY,
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
  is_complete INTEGER NOT NULL CHECK(is_complete IN (0,1)),
  source_id TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS ix_observation_source_time
  ON source_observation(source_id, system_first_seen_at_utc);
CREATE INDEX IF NOT EXISTS ix_event_symbol_state
  ON canonical_event(symbol, event_state, created_at_utc);
CREATE INDEX IF NOT EXISTS ix_order_status_expiry
  ON paper_order(status, valid_until_utc);
CREATE INDEX IF NOT EXISTS ix_position_status
  ON position_lot(symbol, status);
CREATE INDEX IF NOT EXISTS ix_entity_symbol
  ON entity(primary_symbol);
CREATE INDEX IF NOT EXISTS ix_entity_isin
  ON entity(primary_isin);
CREATE INDEX IF NOT EXISTS ix_alias_value
  ON entity_alias(alias_value);
CREATE INDEX IF NOT EXISTS ix_revision_event
  ON event_revision(event_id);
"""
