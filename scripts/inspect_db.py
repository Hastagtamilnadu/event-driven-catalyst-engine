import sqlite3
from pathlib import Path

db_path = Path(r"D:\02_Trading\data\qualitative_event_ledger.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
for t, c in counts.items():
    print(f"{t}: {c}")
