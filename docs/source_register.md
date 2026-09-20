# Source Register: Regulated Upstream Data Feeds

**Specification Reference:** Section 5, Section 27.2, Section 29  
**Version:** 6.0  
**Enforcement:** Mandatory TLS certificate verification; deterministic polling schedules.

---

## Registered Source Feeds

| Source ID | Upstream Feed Description | Mode | Polling Cadence | Base URL | Terms / Legal URL | Cursor Strategy |
|---|---|---|---|---|---|---|
| **`exchange`** | NSE/BSE Corporate Filings & Announcements | `PAPER_SIGNAL` | 15 minutes | `https://www.nseindia.com/companies-listing/corporate-filings-announcements` | `https://www.nseindia.com/terms-of-use` | Monotonic Timestamp |
| **`ratings`** | CRISIL, CARE, ICRA, India Ratings Disclosures | `PAPER_SIGNAL` | Hourly | `https://www.crisil.com/en/home/our-businesses/ratings/rating-actions.html` | `https://www.crisil.com/en/home/terms-and-conditions.html` | Monotonic Timestamp |
| **`tenders`** | GeM & Central Public Procurement Portals | `PAPER_SIGNAL` | 2 hours | `https://gem.gov.in/contracts` | `https://gem.gov.in/terms-and-conditions` | Monotonic Timestamp |
| **`usfda`** | USFDA Drug Approvals & Inspection Database | `PAPER_SIGNAL` | Daily (06:00 IST) | `https://www.fda.gov/drugs/drug-approvals-and-databases` | `https://www.fda.gov/about-fda/about-website/website-disclaimer` | Monotonic Sequence |
| **`parivesh`** | MoEFCC Parivesh Environmental Clearances | `PAPER_SIGNAL` | Daily (07:00 IST) | `https://parivesh.nic.in/` | `https://parivesh.nic.in/terms.html` | Monotonic Timestamp |
| **`transcripts`** | NSE Earnings Call Transcripts & Presentations | `CONTEXT_ONLY` | 4 hours | `https://www.nseindia.com/companies-listing/corporate-filings-transcripts` | `https://www.nseindia.com/terms-of-use` | Monotonic Timestamp |
| **`ownership`** | SEBI SAST & PIT Insider Shareholding Reports | `CONTEXT_ONLY` | Daily (20:00 IST) | `https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern` | `https://www.nseindia.com/terms-of-use` | Monotonic Timestamp |
| **`surveillance`** | NSE/BSE ASM, GSM, ESM & Price Band Registers | `ACTIVE_RISK_OVERLAY` | Twice Daily | `https://www.nseindia.com/reports/surveillance` | `https://www.nseindia.com/terms-of-use` | Monotonic Timestamp |
| **`calendar`** | Exchange Trading Calendar & Holiday Schedules | `PAPER_SIGNAL` | Weekly | `https://www.nseindia.com/resources/exchange-communication-holidays` | `https://www.nseindia.com/terms-of-use` | Monotonic Timestamp |

---

## Health & SLA Invariants (§29.4)
1. **Empty Count Alert:** If an active feed yields 0 records outside configured market holidays, the health monitor flags `SOURCE_UNAVAILABLE`.
2. **Stale Cursor Alert:** If the ingestion cursor fails to advance across 3 scheduled cycles, ingestion is frozen for that feed.
3. **Parse Error Threshold:** A document parsing failure rate $> 2.0\%$ triggers an automatic `INCIDENT_FREEZE_ACTIVE` on that feed.
