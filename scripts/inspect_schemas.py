import sqlite3

conn = sqlite3.connect(r"D:\02_Trading\data\qualitative_event_ledger.db")
print("--- price_bar schema ---")
for col in conn.execute("PRAGMA table_info(price_bar)").fetchall():
    print(col)

print("\n--- corporate_action schema ---")
for col in conn.execute("PRAGMA table_info(corporate_action)").fetchall():
    print(col)

print("\n--- canonical_event schema ---")
for col in conn.execute("PRAGMA table_info(canonical_event)").fetchall():
    print(col)

print("\n--- raw_document schema ---")
for col in conn.execute("PRAGMA table_info(raw_document)").fetchall():
    print(col)

print("\n--- source_observation schema ---")
for col in conn.execute("PRAGMA table_info(source_observation)").fetchall():
    print(col)

print("\n--- extracted_fact schema ---")
for col in conn.execute("PRAGMA table_info(extracted_fact)").fetchall():
    print(col)
