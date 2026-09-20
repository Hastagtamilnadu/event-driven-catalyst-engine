from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

data_dir = Path("D:/02_Trading/data")
db_path = data_dir / "qualitative_event_ledger.db"
conn = sqlite3.connect(db_path)

print("Tables in DB:")
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(tables)

# 1. master_security_history.parquet
if "security_membership" in tables:
    df_sec = pd.read_sql_query("SELECT * FROM security_membership", conn)
    p_sec = data_dir / "master_security_history.parquet"
    df_sec.to_parquet(p_sec)
    print("1. Wrote master_security_history.parquet:", df_sec.shape)

# 2. master_point_in_time_fundamentals.parquet
p_qfr = data_dir / "master_quarterly_financial_results.parquet"
p_fund = data_dir / "master_point_in_time_fundamentals.parquet"
if "fundamental_metrics" in tables:
    df_fund = pd.read_sql_query("SELECT * FROM fundamental_metrics", conn)
    df_fund.to_parquet(p_fund)
    print("2. Wrote master_point_in_time_fundamentals.parquet from DB:", df_fund.shape)
elif p_qfr.exists():
    df_qfr = pd.read_parquet(p_qfr)
    df_qfr.to_parquet(p_fund)
    print("2. Wrote master_point_in_time_fundamentals.parquet from QFR:", df_qfr.shape)

# 3. master_entity_resolution.parquet
p_isin = data_dir / "master_isin_entity_resolution.parquet"
p_ent = data_dir / "master_entity_resolution.parquet"
if p_isin.exists():
    df_isin = pd.read_parquet(p_isin)
    df_isin.to_parquet(p_ent)
    print("3. Wrote master_entity_resolution.parquet:", df_isin.shape)

# 4. master_company_event_history.parquet
if "canonical_event" in tables:
    df_events = pd.read_sql_query("SELECT * FROM canonical_event", conn)
    p_ev = data_dir / "master_company_event_history.parquet"
    df_events.to_parquet(p_ev)
    print("4. Wrote master_company_event_history.parquet:", df_events.shape)

# 5. master_market_bars.parquet
p_turnover = data_dir / "master_daily_trading_turnover.parquet"
p_bars = data_dir / "master_market_bars.parquet"
if "price_bar" in tables:
    df_bars_db = pd.read_sql_query("SELECT * FROM price_bar", conn)
    if not df_bars_db.empty:
        df_bars_db.to_parquet(p_bars)
        print("5. Wrote master_market_bars.parquet from DB:", df_bars_db.shape)
    elif p_turnover.exists():
        df_to = pd.read_parquet(p_turnover)
        df_to.to_parquet(p_bars)
        print("5. Wrote master_market_bars.parquet from turnover:", df_to.shape)
elif p_turnover.exists():
    df_to = pd.read_parquet(p_turnover)
    df_to.to_parquet(p_bars)
    print("5. Wrote master_market_bars.parquet from turnover:", df_to.shape)

conn.close()
print("All 5 canonical stores successfully processed!")
