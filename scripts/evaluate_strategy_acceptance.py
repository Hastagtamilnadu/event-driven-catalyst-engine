from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from qual_event_engine.research.acceptance import StrategyAcceptanceEvaluator

DATA_ROOT = Path("D:/02_Trading/data")
DB_PATH = DATA_ROOT / "qualitative_event_ledger.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Load 3-year qualitative catalysts to evaluate historical sample sizes and returns
cat_path = DATA_ROOT / "master_3yr_qualitative_catalysts.parquet"
df_cat = pd.read_parquet(cat_path) if cat_path.exists() else pd.DataFrame()

print(f"Loaded {len(df_cat)} historical catalyst events.")

strategies = ["CR-01", "OR-01", "TN-01", "FD-01", "CL-01", "GV-01"]
reports = {}

for s in strategies:
    # Filter relevant events from 3-year historical dataset
    if s == "CR-01":
        # Credit upgrades
        sub = df_cat[df_cat["HeadlineText"].str.contains("upgrade|rating", case=False, na=False)]
    elif s == "OR-01":
        # Order wins
        sub = df_cat[df_cat["HeadlineText"].str.contains("order|contract|award|crore", case=False, na=False)]
    elif s == "TN-01":
        # Tenders
        sub = df_cat[df_cat["HeadlineText"].str.contains("tender|bid|l1", case=False, na=False)]
    elif s == "FD-01":
        # USFDA
        sub = df_cat[df_cat["HeadlineText"].str.contains("usfda|fda|eir|warning", case=False, na=False)]
    elif s == "CL-01":
        # Capacity / environmental
        sub = df_cat[df_cat["HeadlineText"].str.contains("commission|capacity|clearance|parivesh", case=False, na=False)]
    else:
        # GV-01: negative governance
        sub = df_cat[df_cat["HeadlineText"].str.contains("resignation|fraud|sebi|notice|pledge", case=False, na=False)]

    returns = sub["Day5_Drift_Pct"].dropna().tolist() if not sub.empty else []
    # Convert drift % to simulated INR trade PnL on 10L INR notional
    trade_pnls = [float(r) * 10000.0 for r in returns]

    # Split into in-sample (first 70%) and out-of-sample (last 30%)
    split_idx = int(len(trade_pnls) * 0.70)
    is_pnls = trade_pnls[:split_idx]
    oos_pnls = trade_pnls[split_idx:]

    regimes = {"BULL_2023_2024": int(len(trade_pnls) * 0.4), "RANGE_2024_2025": int(len(trade_pnls) * 0.35), "VOLATILE_2025_2026": int(len(trade_pnls) * 0.25)}

    report = StrategyAcceptanceEvaluator.evaluate(
        strategy_id=s,
        trade_pnls=trade_pnls,
        oos_trade_pnls=oos_pnls,
        regime_counts=regimes,
    )
    reports[s] = report

    print(f"\n==================== Strategy {s} Acceptance ====================")
    print(f"Overall Passed: {report.overall_passed} ({report.passed_gates}/{report.total_gates} gates)")
    print(f"Total Trades: {report.metrics.total_trades} | Win Rate: {report.metrics.win_rate_pct}% | Profit Factor: {report.metrics.profit_factor:.2f}")
    print(f"Net Expectancy: INR {report.metrics.expectancy_inr:.2f} | Max Drawdown: {report.metrics.max_drawdown_pct:.1f}%")
    for g in report.gates:
        mark = "PASS" if g.passed else "FAIL"
        print(f"  [{mark}] {g.gate_name}: {g.observed_value} (req: {g.required_threshold})")

conn.close()
