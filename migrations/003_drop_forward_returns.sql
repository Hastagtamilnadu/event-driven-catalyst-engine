-- 003_drop_forward_returns.sql
-- Enforces zero-lookahead purity by verifying that no forward return or lookahead column exists in canonical tables

-- Verification query asserting no forward returns in canonical_event
SELECT CASE 
  WHEN EXISTS (
    SELECT 1 FROM pragma_table_info('canonical_event') WHERE name LIKE '%forward%' OR name LIKE '%return%'
  ) THEN RAISE(ABORT, 'Forward return columns detected in canonical_event table!')
  ELSE 'ZERO_LOOKAHEAD_VERIFIED'
END;
