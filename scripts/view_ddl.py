import sqlite3

conn = sqlite3.connect(r"D:\02_Trading\data\qualitative_event_ledger.db")
for t in ["paper_order", "paper_fill", "position_lot", "cash_ledger", "review_decision", "event_revision"]:
    sql = conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{t}'").fetchone()
    print(f"=== {t} ===")
    if sql:
        print(sql[0])
