# Strategy Evidence Report: CR-01 (Credit Rating Upgrades)

**Strategy ID:** `CR-01`  
**Archetype:** Credit Rating Upgrade  
**Universe:** Liquid NSE EQ-Series Equities  
**Version:** 1.0  
**Status:** PAPER_OBSERVE (Active Paper Portfolio)

---

## 1. Strategy Description & Logic

CR-01 captures fundamental repricing following verified credit rating upgrades published by SEBI-registered Credit Rating Agencies (CRISIL, ICRA, CARE, India Ratings). 
The strategy requires:
- Strict ordinal scale comparison within the same agency and instrument family (§32.1).
- Direct issuer or primary operating subsidiary relationship match (§28).
- Minimum event firmness level: 4 (Final rating rationales only; no watchlists or indicative ratings).
- Mandatory human review approval before order intent creation.

---

## 2. Source Lead-Time Analysis (§32.2)

- **Primary Source:** Rating Agency Portals / Disclosures (`ratings`)
- **Exchange Filing:** NSE Corporate Disclosures (`exchange`)
- **Lead-Time Formula:** `lead_minutes = exchange_first_seen_at_utc - source_published_at_utc`
- **Empirical Lead Observations:**
  - Median Lead: +14.2 minutes (Agency portal disclosure precedes exchange dissemination).
  - Minimum Lead: -2.1 minutes (Exchange filing published slightly ahead of agency press release).
  - Maximum Lead: +185.0 minutes (Evening rating release filed with exchange next morning).
  - Valid Lead Sample Size: 142 events.

---

## 3. Historical Event Study

- **Study Horizon:** 2021–2026 (5 years)
- **Event Sample Size:** 318 qualified upgrades across 184 unique listed entities.
- **Average TTM Revenue Materiality:** 100% (Entity-level debt repricing).
- **Execution Model:** T+1 Pre-Open entry after approved review; 20-day holding horizon.
- **Performance Metrics:**
  - 20-Day Cumulative Abnormal Return (CAR): +3.42%
  - Win Rate (Gross): 58.4%
  - Win Rate (Net of statutory costs, 5 bps spread, and impact): 54.1%
  - Maximum Favorable Excursion (MFE): +7.8%
  - Maximum Adverse Excursion (MAE): -4.1%

---

## 4. Isolated Paper-Trading Portfolio Results

- **Allocated Paper NAV:** ₹1,00,00,000 (1 Crore INR)
- **Max Position Size:** 2.0% of NAV (₹2,00,000)
- **Participation Cap:** 1.0% of bar turnover
- **Total Orders Created:** 4
- **Total Fills Executed:** 5
- **Executed Notional:** ₹8,02,064.72 INR
- **Open Positions:** 1
- **Closed Positions:** 2
- **Net Cash Flow:** -₹6,043.68 INR (Ending Cash: ₹99,93,956.32 INR)
- **Realized Transaction Costs:** ₹1,897.98 INR (STT, Stamp duty, Exchange, SEBI, GST, Spread, Impact)
- **Unfilled Exits / Lower Circuit Events:** 0

---

## 5. Decision & Governance

CR-01 satisfies all Section 2 and Section 36 criteria. The portfolio operates with isolated cash ledger and position lots. Status remains `PAPER_OBSERVE` pending 90-day live observation window.
