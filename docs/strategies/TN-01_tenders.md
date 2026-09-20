# Strategy Evidence Report: TN-01 (Tenders & Bid Openings)

**Strategy ID:** `TN-01`  
**Archetype:** Tender & Bid Openings  
**Universe:** Liquid NSE EQ-Series Equities  
**Version:** 1.0  
**Status:** EVIDENCE_ONLY (No Automated Execution)

---

## 1. Strategy Description & Logic

TN-01 tracks public procurement results across Central Public Procurement (CPP) Portal, Government e-Marketplace (GeM), and State/Railways/NHAI tender portals.
- **Mandate (§2.2):** An L1 or preferred-bidder result is NOT assumed to be a binding commercial contract.
- **Rule (§34.2):** An L1 tender disclosure remains evidence-only and creates NO automated paper orders until a definitive Letter of Award (LoA) or signed contract is filed.

---

## 2. Source Lead-Time Analysis (§32.2)

- **Primary Source:** GeM / CPP Portal Bid Evaluation Logs (`tenders`)
- **Exchange Filing:** NSE Corporate Disclosures (`exchange`)
- **Empirical Lead Observations:**
  - Median Lead: +48.5 hours (L1 bid status published on portal days before formal contract award).
  - Caveat: ~38% of L1 bids undergo price negotiation, challenge, or cancellation and never materialize into exchange-filed contract awards.
  - Valid Observation Sample: 89 tenders.

---

## 3. Historical Event Study & Conversion Reality

- **Sample Size:** 215 L1 announcements (2022–2026).
- **Conversion to Binding LoA:** 61.4%
- **Event Study on Raw L1 Announcement:**
  - 5-Day CAR: +1.15% (Often met with immediate profit taking or reversal upon negotiation delays).
  - False Positive Drag: Canceled or challenged tenders experienced an average 20-day CAR of -5.8%.
- **Conclusion:** Trading raw L1 notices produces negative risk-adjusted returns after factoring in execution friction and cancellation probability.

---

## 4. Isolated Paper-Trading Portfolio Status

- **Status:** `PAPER_OBSERVE` (Definitive Level-4/5 Tenders)
- **Allocated Paper NAV:** ₹1,00,00,000 (1 Crore INR)
- **Max Position Size:** 2.0% of NAV (₹2,00,000)
- **Participation Cap:** 1.0% of bar turnover
- **Total Orders Created:** 1
- **Total Fills Executed:** 1
- **Executed Notional:** ₹1,91,803.55 INR
- **Open Positions:** 1
- **Closed Positions:** 0
- **Net Cash Flow:** -₹1,91,803.55 INR (Ending Cash: ₹98,08,196.45 INR)
- **Realized Transaction Costs:** ₹432.80 INR
- **Evidence Records Logged:** 89 tender observations linked in canonical ledger.
- **Reason:** Protection against non-binding contract inflation in public sector bidding. Level < 4 remains evidence only.
