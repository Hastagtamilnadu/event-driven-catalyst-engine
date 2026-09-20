# Decision Log: Quantitative & Architectural Records

**Specification Reference:** Section 26, Section 33  
**Version:** 6.0  
**Status:** Canonical Decision History

---

## Architectural Decisions

### ADR-001: SQLite WAL Mode for Canonical Transactional Ledger
- **Date:** 2026-09-15
- **Status:** APPROVED
- **Context:** The platform requires deterministic, crash-safe, local relational persistence for events, revisions, model notes, paper orders, fills, and double-entry cash accounting.
- **Decision:** Use SQLite with `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = WAL;`, `PRAGMA synchronous = FULL;`, and `PRAGMA busy_timeout = 5000;`. All mutations are committed via serial transactions.
- **Consequences:** Provides absolute zero-orphan referential integrity and concurrent read capability for the Review UI without locking background ingestion.

### ADR-002: Strict Two-Stage AI Pipeline with Verbatim Substring Grounding
- **Date:** 2026-09-18
- **Status:** APPROVED
- **Context:** LLMs are prone to hallucinating citations or asserting false causal certainty regarding price action.
- **Decision:** Mandate a two-stage pipeline:
  1. Stage 1 `extract_facts()` extracts structured fields and exact verbatim text excerpts from the raw document.
  2. Deterministic Python validator asserts that every excerpt is an exact character-for-character substring of the raw document.
  3. If grounding fails on any fact, the event is immediately marked `BLOCKED`, and Stage 2 `assess()` is aborted (zero LLM calls, zero paper orders).
  4. Only verified facts and point-in-time financial dossiers are passed to Stage 2.
- **Consequences:** Eliminates hallucinated facts from entering strategy eligibility gates or portfolio orders.

### ADR-003: Exclusion of Forward Returns from Decision Models (§30.2)
- **Date:** 2026-09-19
- **Status:** APPROVED
- **Context:** Historical catalyst research datasets often append forward-return columns (`ret_1d`, `ret_5d`, `ret_20d`). These induce fatal look-ahead bias if exposed to decision models.
- **Decision:** Migration 003 physically dropped all forward-return columns from the core transactional schema. Forward returns are strictly segregated into post-hoc research output tables only.
- **Consequences:** Guarantees zero look-ahead bias across all replay and real-time execution pipelines.

### ADR-004: Parquet Canonical Stores for Analytical Research (§6)
- **Date:** 2026-09-20
- **Status:** APPROVED
- **Context:** Section 6 mandates 5 canonical parquet stores for security history, point-in-time fundamentals, entity resolution, company events, and market bars.
- **Decision:** Export and maintain versioned parquet stores in `D:\02_Trading\data/` that are actively consumed by the market data, universe, and replay engines.
- **Consequences:** Enables high-performance columnar analytical queries and backtests while keeping SQLite dedicated to transactional order/cash ledger integrity.
