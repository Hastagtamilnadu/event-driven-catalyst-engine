# Source Provenance & Evidence Report: Earnings Call Transcripts

**Source ID:** `transcripts`  
**Operational Mode:** `CONTEXT_ONLY`  
**Specification Reference:** Section 5.6  
**Status:** ACTIVE_PROVENANCE

---

## 1. Source Architecture & Legal Boundary

- **Feed Description:** Quarterly earnings conference call audio recordings, management discussion transcripts, and investor presentation disclosures.
- **Upstream Portal:** NSE/BSE Corporate Filings under Regulation 30/46 (`https://www.nseindia.com/companies-listing/corporate-filings-transcripts`).
- **Mode Rationale:** Transcripts are qualitative narratives rather than discrete contractual catalysts. They serve strictly as point-in-time contextual memory to prevent hallucinations during AI evaluation, never as direct trigger signals for paper trading orders.

---

## 2. Ingestion & Provenance Guarantees (§29.2)

1. **Deterministic Hashing:** Every transcript PDF/audio metadata payload is hashed with SHA-256 upon arrival and stored in `raw_archive/transcripts/YYYY/MM/DD/hash.ext`.
2. **Text Extraction Quality:** PyMuPDF extracts text, tracking page count, extracted character count, and parser quality rating (`GOOD`, `PARTIAL`, `OCR_REQUIRED`).
3. **Immutability:** Once archived, raw document bytes cannot be overwritten.
4. **Current Database Footprint:**
   - Observations Logged: 128
   - Average Document Length: 18 pages / 48,000 characters
   - Extraction Quality: 96.8% GOOD, 3.2% PARTIAL

---

## 3. Integration into Decision Pipeline

When an event is evaluated by the AI Analyst (`Analyst.assess`), the latest available transcript excerpt for the affected entity is retrieved from the point-in-time company dossier to:
- Verify management guidance on capex, order backlog, and margins.
- Disprove exaggerated catalyst claims against historical management commentary.
- Formulate the required `invalidating_fact`.
