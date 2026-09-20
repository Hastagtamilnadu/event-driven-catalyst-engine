# Source Provenance & Evidence Report: Ownership & Insider Disclosures

**Source ID:** `ownership`  
**Operational Mode:** `CONTEXT_ONLY`  
**Specification Reference:** Section 5.7  
**Status:** ACTIVE_PROVENANCE

---

## 1. Source Architecture & Legal Boundary

- **Feed Description:** SEBI Substantial Acquisition of Shares and Takeovers (SAST) disclosures, SEBI Prohibition of Insider Trading (PIT) Form C disclosures, and quarterly Shareholding Patterns (SHP).
- **Upstream Portal:** NSE/BSE Corporate Filings (`https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern`).
- **Mode Rationale:** Institutional accumulation and promoter pledges provide vital balance sheet and governance context, but do not satisfy the criteria for discrete, event-driven paper execution.

---

## 2. Ingestion & Provenance Guarantees (§29.2)

1. **Deterministic Hashing:** All XML/XBRL/JSON/PDF ownership filings are hashed with SHA-256 and archived in `raw_archive/ownership/YYYY/MM/DD/hash.ext`.
2. **Entity Resolution (§28):** Filings are linked to the primary entity via ISIN and validated promoter/director aliases in `entity_alias`.
3. **Current Database Footprint:**
   - Observations Logged: 310
   - Promoter Pledge Changes Tracked: 42
   - Bulk / Block Deals Logged: 184

---

## 3. Integration into Decision Pipeline

Ownership disclosures feed the point-in-time dossier during event evaluation:
- High promoter pledge (>25%) flags a warning in the dossier and downgrades event eligibility.
- Substantial insider selling by key managerial personnel immediately preceding a positive announcement flags a risk-gate alert (`HIGH_INSIDER_SELLING`).
