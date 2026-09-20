-- 001_initial_schema.sql
-- Baseline schema for qualitative event-driven equity research and paper trading

CREATE TABLE IF NOT EXISTS security_membership (
  membership_id TEXT PRIMARY KEY,
  isin TEXT,
  symbol TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  effective_from_utc TEXT NOT NULL,
  effective_to_utc TEXT,
  series TEXT NOT NULL DEFAULT 'EQ',
  listed_status TEXT NOT NULL DEFAULT 'ACTIVE',
  surveillance_status TEXT NOT NULL DEFAULT 'NONE',
  price_band_pct REAL,
  market_cap_inr REAL,
  adv20_shares REAL,
  adt20_inr REAL,
  eligible INTEGER NOT NULL DEFAULT 1,
  eligibility_reasons TEXT NOT NULL DEFAULT '[]',
  source_id TEXT NOT NULL,
  source_version TEXT NOT NULL,
  UNIQUE(symbol, effective_from_utc, source_version)
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
  job_run_id TEXT NOT NULL,
  UNIQUE(source_id, source_native_id, raw_sha256)
);

CREATE TABLE IF NOT EXISTS raw_document (
  raw_sha256 TEXT PRIMARY KEY,
  local_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  page_count INTEGER,
  extracted_characters INTEGER NOT NULL,
  extraction_quality TEXT NOT NULL,
  archived_at_utc TEXT NOT NULL,
  parser_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canonical_event (
  event_id TEXT PRIMARY KEY,
  observation_id TEXT NOT NULL REFERENCES source_observation(observation_id),
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
