import sqlite3

conn = sqlite3.connect(r"D:\02_Trading\data\qualitative_event_ledger.db")
for table in ["paper_order", "paper_fill", "position_lot", "cash_ledger", "analyst_assessment"]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    print(f"--- {table} ({len(rows)} rows) ---")
    for r in rows:
        print(r)
