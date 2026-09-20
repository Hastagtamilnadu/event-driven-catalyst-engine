# Runbook: Monthly Audit & Evidence Generation (RB-09)

## 1. Detection
- First non-holiday business day of each calendar month.
- Trigger for `QualEngine_MonthlyAudit` scheduled job.

## 2. Immediate Freeze Action
- Monthly audit runs in read-only analysis mode.
- Does not freeze active trading operations unless a critical audit failure is detected.

## 3. Diagnosis & Audit Checklist
1. Model Benchmark Suite:
   - Run `uv run pytest tests/test_benchmarks.py`.
   - Verify 20/20 fixtures pass; assert 0 hallucinations and 0 prohibited certainty claims.
2. Source Timing & Lead-Time Distribution:
   - Run `uv run qual-engine report --report lead-time`.
   - Measure dissemination lead-time distribution $\Delta t = t_{\text{trade}} - t_{\text{dissemination}}$ by source.
3. Strategy Attribution & Evidence:
   - Run `uv run qual-engine report --report performance`.
   - Verify isolated P&L, Sharpe ratio, win rate, and max drawdown by strategy.
4. Database & Snapshot Integrity:
   - Verify monthly immutable research snapshot in `data/backups/snapshots/`.
   - Run `PRAGMA integrity_check;` on snapshot.

## 4. Recovery
1. If model benchmark regression occurs: freeze prompt version changes; investigate changed candidate outputs.
2. If lead time deteriorates: flag upstream source latency for review.
3. If reconciliation mismatch detected: execute RB-05 (Paper Reconciliation).

## 5. Reconciliation
1. Compare monthly P&L sum against daily cash ledger entries.
2. Verify all open position lots have valid current market marks.
3. Verify that corporate action adjustments were correctly applied.

## 6. Closure Evidence
- Monthly report generated and saved to `data/reports/YYYY-MM/audit_report.json`.
- Signed off by lead researcher and operator.
- Archive manifest hash recorded in `job_run`.

## 7. Prevention Action
- Review model provider updates, deprecation notices, and benchmark trends monthly.
- Maintain immutable snapshot retention for multi-year strategy backtesting.
