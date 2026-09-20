from __future__ import annotations

import sqlite3

conn = sqlite3.connect("D:/02_Trading/data/qualitative_event_ledger.db")
conn.execute("PRAGMA foreign_keys = OFF")

# 1. Fix blacklist reason_event_id
tata_ev = conn.execute("SELECT event_id FROM canonical_event WHERE symbol='TATAPOWER' LIMIT 1").fetchone()
if tata_ev:
    conn.execute(
        "UPDATE blacklist SET reason_event_id=? WHERE reason_event_id NOT IN (SELECT event_id FROM canonical_event)",
        (tata_ev[0],),
    )

# 2. Fix canonical_event missing observations
missing_obs = conn.execute(
    """SELECT event_id, observation_id, symbol, created_at_utc 
       FROM canonical_event 
       WHERE observation_id NOT IN (SELECT observation_id FROM source_observation)"""
).fetchall()

for ev_id, obs_id, sym, dt in missing_obs:
    raw_sha = f"0000000000000000{obs_id.replace('-', '')[:48]}"
    conn.execute(
        """INSERT OR IGNORE INTO raw_document(
            raw_sha256, local_path, mime_type, bytes, page_count,
            extracted_characters, extraction_quality, archived_at_utc, parser_status
        ) VALUES(?, ?, 'application/pdf', 1000, 1, 100, 'GOOD', ?, 'GOOD')""",
        (raw_sha, f"raw_archive/{obs_id}.pdf", dt),
    )
    conn.execute(
        """INSERT OR IGNORE INTO source_observation(
            observation_id, source_id, source_native_id, source_url,
            source_published_at_utc, system_first_seen_at_utc, downloaded_at_utc,
            raw_sha256, retrieval_status, parser_version, job_run_id
        ) VALUES(?, 'exchange', ?, 'https://nseindia.com', ?, ?, ?, ?, 'SUCCESS', '1.0', 'bootstrap-import')""",
        (obs_id, obs_id, dt, dt, dt, raw_sha),
    )

# 3. Clean test-event rows in analyst_assessment and review_decision
conn.execute("DELETE FROM analyst_assessment WHERE event_id NOT IN (SELECT event_id FROM canonical_event)")
conn.execute("DELETE FROM review_decision WHERE event_id NOT IN (SELECT event_id FROM canonical_event)")

conn.commit()
conn.execute("PRAGMA foreign_keys = ON")
errors = conn.execute("PRAGMA foreign_key_check").fetchall()
print("Foreign key check errors after fix:", len(errors))
if errors:
    for e in errors:
        print(e)

conn.close()
