# Data Dictionary: Qualitative Event-Driven Equity Research and Paper-Trading System

**Specification Reference:** Section 6, Section 28  
**Version:** 6.0  
**Storage Engine:** SQLite WAL Ledger (`qualitative_event_ledger.db`) & Canonical Parquet Stores

---

## 1. Core Ledger Tables

### `schema_migration`
Tracks versioned, repeatable DDL migrations with cryptographic checksums.
- `version` (TEXT PRIMARY KEY): Migration version identifier (e.g. `001_initial_schema`).
- `applied_at_utc` (TEXT NOT NULL): ISO-8601 UTC timestamp of application.
- `checksum_sha256` (TEXT NOT NULL): SHA-256 hash of migration SQL file.

### `job_run`
Tracks scheduled job runs, exit states, and runtime configuration hashes.
- `job_run_id` (TEXT PRIMARY KEY): Unique run identifier.
- `job_name` (TEXT NOT NULL): Canonical job name (e.g. `QualEngine_Morning`).
- `started_at_utc` (TEXT NOT NULL): Start timestamp.
- `finished_at_utc` (TEXT): Completion timestamp.
- `status` (TEXT NOT NULL): Status (`STARTED`, `SUCCEEDED`, `FAILED`, `BLOCKED`).
- `config_hash` (TEXT NOT NULL): SHA-256 hash of active configuration book.
- `code_version` (TEXT NOT NULL): Code release version (e.g. `6.0`).
- `error_summary` (TEXT): Error message if failed.

### `raw_document`
Immutable raw document storage organized by SHA-256 content hash.
- `raw_sha256` (TEXT PRIMARY KEY): Content hash.
- `local_path` (TEXT NOT NULL UNIQUE): Relative archive path (`source_id/YYYY/MM/DD/hash.ext`).
- `mime_type` (TEXT): Detected MIME type from magic bytes.
- `bytes` (INTEGER NOT NULL): File size in bytes.
- `page_count` (INTEGER): Extracted document page count.
- `extracted_characters` (INTEGER): Number of text characters extracted.
- `extraction_quality` (TEXT NOT NULL): Classification (`GOOD`, `PARTIAL`, `OCR_REQUIRED`, `UNSUPPORTED`, `MALICIOUS`).
- `archived_at_utc` (TEXT NOT NULL): Timestamp of archival.
- `malware_scan_status` (TEXT NOT NULL): Status (`CLEAN`, `QUARANTINED`).
- `parser_status` (TEXT NOT NULL): Parser status (`PARSED`, `FAILED`).

### `source_observation`
Tracks ingestion provenance, timestamps, and retrieval metadata for each document.
- `observation_id` (TEXT PRIMARY KEY): Observation identifier.
- `source_id` (TEXT NOT NULL): Source identifier (e.g. `exchange`, `ratings`).
- `source_native_id` (TEXT): Upstream portal disclosure ID.
- `source_url` (TEXT NOT NULL): Source URL.
- `source_published_at_utc` (TEXT): Upstream publication timestamp.
- `source_document_date` (TEXT): Document date cited in text.
- `system_first_seen_at_utc` (TEXT NOT NULL): System discovery timestamp.
- `downloaded_at_utc` (TEXT): Download timestamp.
- `exchange_first_seen_at_utc` (TEXT): Exchange availability timestamp.
- `raw_sha256` (TEXT): References `raw_document(raw_sha256)`.
- `retrieval_status` (TEXT NOT NULL): Retrieval outcome (`ARCHIVED`, `FAILED`).
- `http_status` (INTEGER): HTTP response code.
- `parser_version` (TEXT): Parser code version.
- `timezone_original` (TEXT): Original timezone of filing.
- `supersedes_observation_id` (TEXT): Self-reference for amendments.
- `job_run_id` (TEXT NOT NULL): References `job_run(job_run_id)`.

### `entity`
Legal entity master resolving listed and unlisted corporate identities.
- `entity_id` (TEXT PRIMARY KEY): Unique entity ID.
- `isin` (TEXT UNIQUE): Primary equity ISIN.
- `cin` (TEXT): Corporate Identification Number.
- `legal_name` (TEXT NOT NULL): Registered legal corporate name.
- `entity_type` (TEXT NOT NULL): Type (`LISTED_EQUITY`, `SUBSIDIARY`, `JOINT_VENTURE`, `SPECIAL_PURPOSE_VEHICLE`).
- `active_from` (TEXT): Effective inception date.
- `active_to` (TEXT): Dissolution or delisting date.

### `canonical_event`
Immutable corporate event records promoted from validated observations.
- `event_id` (TEXT PRIMARY KEY): Canonical event identifier.
- `entity_id` (TEXT REFERENCES entity): Resolved entity.
- `isin` (TEXT): Equity ISIN.
- `symbol` (TEXT): Official exchange symbol.
- `event_type` (TEXT NOT NULL): Taxonomy classification (`CREDIT_UPGRADE`, `ORDER_AWARD`, `TENDER_AWARD`, `USFDA_FINAL_CLASSIFICATION`, `CAPACITY_EXPANSION`, `NEGATIVE_GOVERNANCE`).
- `event_status` (TEXT NOT NULL): Lifecycle status (`FINAL`, `AMENDED`, `CANCELLED`).
- `event_occurred_at_utc` (TEXT): Physical event occurrence timestamp.
- `decision_eligible_at_utc` (TEXT): Point-in-time eligibility timestamp.
- `entity_match_status` (TEXT NOT NULL): Entity match certainty (`VERIFIED`, `NEEDS_REVIEW`).
- `event_state` (TEXT NOT NULL): State machine state (`INGESTED`, `APPROVED`, `REJECTED`, `BLOCKED`).
- `created_at_utc` (TEXT NOT NULL): Record creation timestamp.
- `latest_revision_number` (INTEGER NOT NULL DEFAULT 1): Current revision counter.

### `event_revision`
Audit trail of amendments, corrections, and retractions to canonical events.
- `event_revision_id` (TEXT PRIMARY KEY): Revision identifier.
- `event_id` (TEXT NOT NULL REFERENCES canonical_event): Linked canonical event.
- `observation_id` (TEXT NOT NULL REFERENCES source_observation): Source observation.
- `revision_number` (INTEGER NOT NULL): Monotonic revision index.
- `revision_kind` (TEXT NOT NULL): Kind (`INITIAL`, `AMENDMENT`, `CANCELLATION`, `CORRECTION`).
- `material_change_flag` (INTEGER NOT NULL): 1 if material economic terms changed, 0 otherwise.
- `superseded_at_utc` (TEXT): Timestamp when superseded by a later revision.

### `extracted_fact`
Deterministic facts extracted from filing text with verbatim quotes.
- `fact_id` (TEXT PRIMARY KEY): Unique fact ID.
- `event_revision_id` (TEXT NOT NULL REFERENCES event_revision): Linked revision.
- `field_name` (TEXT NOT NULL): Canonical field name.
- `value_json` (TEXT): Structured JSON value.
- `value_normalized` (TEXT): Normalized scalar value.
- `page_number` (INTEGER): Document page where fact appears.
- `evidence_text` (TEXT NOT NULL): Exact verbatim quote from filing.
- `extractor_name` (TEXT NOT NULL): Name of extraction module.
- `extractor_version` (TEXT NOT NULL): Extractor version.
- `confidence` (REAL NOT NULL): Confidence score ($0.0 \le c \le 1.0$).
- `validation_status` (TEXT NOT NULL): Status (`VERIFIED`, `UNGROUNDED`, `REJECTED`).

### `analyst_assessment`
AI research assessment records generated by LLM reasoning.
- `assessment_id` (TEXT PRIMARY KEY): Assessment identifier.
- `event_revision_id` (TEXT NOT NULL REFERENCES event_revision): Linked revision.
- `dossier_hash` (TEXT NOT NULL): SHA-256 of point-in-time company dossier.
- `model_id` (TEXT NOT NULL): AI model identifier.
- `model_version` (TEXT NOT NULL): Model release version.
- `prompt_version` (TEXT NOT NULL): Prompt version hash.
- `input_hash` (TEXT NOT NULL): Hash of prompt input payload.
- `output_hash` (TEXT NOT NULL): Hash of raw model response.
- `recommendation` (TEXT NOT NULL): Decision recommendation (`BUY_CANDIDATE`, `WATCH`, `PASS`, `BLOCK`).
- `rationale` (TEXT NOT NULL): Concise research thesis.
- `invalidating_fact` (TEXT NOT NULL): The single fact most likely to disprove thesis.
- `schema_valid` (INTEGER NOT NULL): 1 if schema parsed cleanly, 0 otherwise.
- `semantic_valid` (INTEGER NOT NULL): 1 if semantic grounding assertions passed, 0 otherwise.
- `latency_ms` (INTEGER): API round-trip latency in milliseconds.
- `created_at_utc` (TEXT NOT NULL): Record creation timestamp.

### `paper_order`
Simulated order intents generated by strategies following review.
- `paper_order_id` (TEXT PRIMARY KEY): Order ID.
- `client_order_id` (TEXT NOT NULL UNIQUE): Idempotent client order identifier.
- `event_id` (TEXT NOT NULL REFERENCES canonical_event): Linked catalyst event.
- `strategy_id` (TEXT NOT NULL): Strategy identifier (e.g. `CR-01`, `OR-01`).
- `strategy_version` (TEXT NOT NULL): Strategy configuration version.
- `symbol` (TEXT NOT NULL): Exchange symbol.
- `isin` (TEXT): Security ISIN.
- `side` (TEXT NOT NULL): Side (`BUY`, `SELL`).
- `quantity_requested` (INTEGER NOT NULL): Requested share quantity.
- `quantity_remaining` (INTEGER NOT NULL): Unfilled share quantity.
- `order_type` (TEXT NOT NULL): Type (`PAPER_MARKET`, `PAPER_LIMIT`).
- `limit_price` (REAL): Limit price threshold.
- `participation_cap` (REAL NOT NULL): Maximum participation cap of bar volume.
- `valid_from_utc` (TEXT NOT NULL): Order activation timestamp.
- `valid_until_utc` (TEXT NOT NULL): Order expiration timestamp.
- `status` (TEXT NOT NULL): Status (`PENDING_PRICE`, `PARTIALLY_FILLED`, `FILLED`, `EXPIRED`, `EXIT_UNFILLED`).
- `decision_snapshot_hash` (TEXT NOT NULL): SHA-256 hash of decision inputs.
- `created_at_utc` (TEXT NOT NULL): Order creation timestamp.

### `paper_fill`
Simulated fill executions matching orders against chronologically sequenced market bars.
- `paper_fill_id` (TEXT PRIMARY KEY): Fill ID.
- `paper_order_id` (TEXT NOT NULL REFERENCES paper_order): Linked order.
- `filled_at_utc` (TEXT NOT NULL): Execution timestamp.
- `quantity` (INTEGER NOT NULL): Executed share quantity.
- `raw_price` (REAL NOT NULL): Execution price before friction.
- `spread_cost_inr` (REAL NOT NULL): Bid-ask spread cost in INR.
- `impact_cost_inr` (REAL NOT NULL): Market impact penalty in INR.
- `statutory_cost_inr` (REAL NOT NULL): STT, turnover charges, GST, stamp duty.
- `final_price` (REAL NOT NULL): Net effective execution price.
- `fill_reason` (TEXT NOT NULL): Fill categorization (`NORMAL_FILL`, `GAP_OPEN_FILL`).
- `market_data_ref` (TEXT NOT NULL): Identifier of market bar matching fill.

### `position_lot`
Tracks open and closed portfolio positions at the lot level.
- `position_lot_id` (TEXT PRIMARY KEY): Position lot ID.
- `isin` (TEXT NOT NULL): Security ISIN.
- `symbol` (TEXT NOT NULL): Exchange symbol.
- `strategy_id` (TEXT NOT NULL): Strategy ID owning lot.
- `event_id` (TEXT NOT NULL REFERENCES canonical_event): Catalyst event opening lot.
- `opened_by_fill_id` (TEXT NOT NULL REFERENCES paper_fill): Fill creating lot.
- `opened_at_utc` (TEXT NOT NULL): Opening timestamp.
- `quantity_open` (INTEGER NOT NULL): Remaining open shares.
- `average_cost` (REAL NOT NULL): Cost basis per share including transaction friction.
- `stop_price` (REAL): Active stop price.
- `status` (TEXT NOT NULL): Lot status (`OPEN`, `CLOSED`).

### `cash_ledger`
Double-entry cash accounting ledger recording all debits, credits, and strategy balances.
- `cash_entry_id` (TEXT PRIMARY KEY): Unique entry ID.
- `strategy_id` (TEXT NOT NULL): Strategy ID.
- `occurred_at_utc` (TEXT NOT NULL): Timestamp of cash movement.
- `entry_type` (TEXT NOT NULL): Type (`INITIAL_CAPITAL`, `FILL`, `DIVIDEND`, `FEE`).
- `reference_id` (TEXT NOT NULL): Linked fill or corporate action ID.
- `amount_inr` (REAL NOT NULL): Signed cash flow amount in INR.
- `balance_after_inr` (REAL NOT NULL): Strategy cash balance following transaction.

### `incident`
Operational incident ledger tracking system freezes, outages, and recovery workflows.
- `incident_id` (TEXT PRIMARY KEY): Unique incident identifier.
- `severity` (TEXT NOT NULL): Severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`).
- `service` (TEXT NOT NULL): Affected subsystem (`PARSER`, `MODEL`, `SOURCE`, `DATABASE`, `SCHEDULER`).
- `opened_at_utc` (TEXT NOT NULL): Inception timestamp.
- `closed_at_utc` (TEXT): Resolution timestamp.
- `status` (TEXT NOT NULL): Status (`OPEN`, `INVESTIGATING`, `CLOSED`).
- `summary` (TEXT NOT NULL): Problem summary.
- `resolution` (TEXT): Resolution rationale and root cause analysis.
