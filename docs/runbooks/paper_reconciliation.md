# Runbook: Paper Reconciliation (RB-05)

## 1. Detection
- End-of-day reconciliation query identifies discrepancy between `paper_order`, `paper_fill`, `position_lot`, and `cash_ledger`.
- Dangling fill detected without an associated order (`paper_fill.paper_order_id` not found in `paper_order`).
- Position lot has negative open quantity (`quantity_open < 0`).
- Cash ledger balance does not match cumulative sum of cash entries and fill notional/costs.
- Position status is `OPEN` but market price is missing for mark-to-market.

## 2. Immediate Freeze Action
- Freeze new paper order intent generation across all strategies.
- Prevent execution simulator from processing new fills.
- Log incident in `incident` table with severity `CRITICAL`.
- Do NOT delete or overwrite existing ledger records; all fixes must be additive correcting entries.

## 3. Diagnosis
1. Query orders vs fills:
   ```sql
   SELECT o.paper_order_id, o.quantity_requested, sum(f.quantity) as filled_qty
   FROM paper_order o LEFT JOIN paper_fill f ON o.paper_order_id=f.paper_order_id
   GROUP BY o.paper_order_id HAVING filled_qty > o.quantity_requested;
   ```
2. Query position lots vs fills:
   ```sql
   SELECT p.position_lot_id, p.opened_by_fill_id, f.quantity
   FROM position_lot p LEFT JOIN paper_fill f ON p.opened_by_fill_id=f.paper_fill_id
   WHERE f.paper_fill_id IS NULL;
   ```
3. Check cash ledger balance continuity:
   ```sql
   SELECT strategy_id, sum(amount_inr) as calculated_cash, max(balance_after_inr) as recorded_cash
   FROM cash_ledger GROUP BY strategy_id;
   ```

## 4. Recovery
1. Identify the unlinked or mismatched transaction.
2. Insert explicit correcting entry in `cash_ledger` with `entry_type='CORRECTION'` and reference to the incident ID.
3. If position lot quantity was miscalculated, create correcting adjustment lot with immutable audit rationale.
4. Verify all foreign keys and transaction hashes tie out.

## 5. Reconciliation
1. Run reconciliation report: `uv run qual-engine report --report performance`.
2. Confirm `calculated_cash == recorded_cash` for all active strategy portfolios.
3. Confirm sum of open position lots matches net portfolio equity.

## 6. Closure Evidence
- Reconciliation report shows 0 discrepancies.
- Zero orphaned rows in `paper_order`, `paper_fill`, `position_lot`, `cash_ledger`.
- Incident report updated in `incident` table with reviewer approval.

## 7. Prevention Action
- Ensure database transactions wrap order fill, lot creation, and cash debit atomically.
- Run automated post-market reconciliation job daily at 16:00 IST.
