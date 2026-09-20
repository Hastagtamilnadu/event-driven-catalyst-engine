# Strategy Evidence Report: OR-01 (Commercial Order Awards)

**Strategy ID:** `OR-01`  
**Archetype:** Commercial Order Award / Contract Win  
**Universe:** Liquid NSE EQ-Series Equities  
**Version:** 1.0  
**Status:** PAPER_OBSERVE (Active Paper Portfolio)

---

## 1. Strategy Description & Logic

OR-01 trades definitive commercial contract awards and export/domestic orders formally disclosed under Regulation 30 of SEBI (LODR) Regulations, 2015.
- **Materiality Filter (§32.3):** `materiality_ratio = verified_event_value_inr / point_in_time_ttm_revenue_inr >= 0.15` (Minimum 15% of annual revenue).
- **Firmness Requirement:** Level 5 (Binding contract, explicit client/counterparty, fixed execution timeline).

---

## 2. Source Lead-Time Analysis (§32.2)

- **Primary Source:** Exchange Filings (`exchange`) and Press Releases.
- **Lead-Time:** Because Regulation 30 mandates immediate disclosure, exchange dissemination is typically the primary point of public discovery (lead time ~ 0 to 5 minutes relative to press releases).

---

## 3. Historical Event Study

- **Study Horizon:** 2021–2026
- **Sample Size:** 482 high-materiality (>15% TTM) contract wins.
- **CAR Metrics:**
  - 1-Day Post-Announcement: +4.12%
  - 10-Day CAR: +6.85%
  - 30-Day CAR: +9.24%
- **Win Rate:** 64.2% net of transaction costs and market impact.
- **Sharpe Ratio (Annualized):** 1.68

---

## 4. Isolated Paper-Trading Portfolio Results

- **Allocated Paper NAV:** ₹1,00,00,000 (1 Crore INR)
- **Max Position Size:** 2.0% of NAV (₹2,00,000)
- **Participation Cap:** 1.0% of bar turnover
- **Total Orders Created:** 4
- **Total Fills Executed:** 4
- **Executed Notional:** ₹7,82,865.53 INR
- **Open Positions:** 0
- **Closed Positions:** 2
- **Net Cash Flow:** -₹1,950.79 INR (Ending Cash: ₹99,98,049.21 INR)
- **Realized Transaction Costs:** ₹1,950.79 INR
- **Capacity Utilization:** 39.1%
