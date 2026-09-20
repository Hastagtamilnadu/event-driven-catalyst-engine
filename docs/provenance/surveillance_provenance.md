# Source Provenance & Evidence Report: Exchange Surveillance & Risk Overlays

**Source ID:** `surveillance`  
**Operational Mode:** `ACTIVE_RISK_OVERLAY`  
**Specification Reference:** Section 5.8  
**Status:** ACTIVE_PROVENANCE

---

## 1. Source Architecture & Legal Boundary

- **Feed Description:** Daily exchange surveillance lists: Additional Surveillance Measure (ASM - Long Term / Short Term), Enhanced Surveillance Measure (ESM - Stage I / II), Graded Surveillance Measure (GSM), and daily scrip price band revisions (2%, 5%, 10%, 20%).
- **Upstream Portal:** NSE Surveillance Reports (`https://www.nseindia.com/reports/surveillance`).
- **Mode Rationale:** Securities under ASM/ESM/GSM or with restricted 2%/5% price bands carry severe liquidity risk, high margin requirements (up to 100%), and elevated probability of circuit-locked halts. They must immediately disqualify or restrict paper order creation.

---

## 2. Ingestion & Provenance Guarantees (§29.2)

1. **Daily Morning Ingestion:** Processed at 08:00 IST by `QualEngine_Morning` before pre-open intent creation.
2. **Deterministic Hashing:** CSV/JSON surveillance lists are hashed with SHA-256 and archived in `raw_archive/surveillance/YYYY/MM/DD/hash.ext`.
3. **Current Database Footprint:**
   - Active Surveillance Records: 142
   - Daily Price Band Adjustments: 2,302 symbols tracked in `security_membership`.

---

## 3. Active Risk Overlay Enforcement (§15, §32.5)

- **Entry Gate Disqualification:** Any security under Short-Term ASM, ESM Stage II, GSM, or with a price band < 10% is marked `INELIGIBLE` in `security_membership` and rejected by `entry_gate()`.
- **Existing Position Protection:** If an open position's security enters ASM/ESM, the strategy policy evaluates whether to liquidate or freeze new additions.
