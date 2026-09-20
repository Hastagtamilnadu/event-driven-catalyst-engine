-- 002_views_and_indexes.sql
-- Indexes and views for fast lookup and integrity enforcement

CREATE INDEX IF NOT EXISTS ix_security_symbol_effective ON security_membership(symbol, effective_from_utc);
CREATE INDEX IF NOT EXISTS ix_obs_sha ON source_observation(raw_sha256);
CREATE INDEX IF NOT EXISTS ix_event_symbol_created ON canonical_event(symbol, created_at_utc);
CREATE INDEX IF NOT EXISTS ix_event_state ON canonical_event(event_state);
CREATE INDEX IF NOT EXISTS ix_entity_symbol ON entity(primary_symbol);
CREATE INDEX IF NOT EXISTS ix_entity_isin ON entity(primary_isin);
CREATE INDEX IF NOT EXISTS ix_alias_value ON entity_alias(alias_value);
CREATE INDEX IF NOT EXISTS ix_revision_event ON event_revision(event_id);
