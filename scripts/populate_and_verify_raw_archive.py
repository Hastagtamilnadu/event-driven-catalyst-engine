from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

data_dir = Path("D:/02_Trading/data")
db_path = data_dir / "qualitative_event_ledger.db"
archive_dir = data_dir / "raw_archive"
archive_dir.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Query all raw_document joined with source_observation
query = """
    SELECT d.raw_sha256, d.local_path, d.mime_type, d.bytes, d.extracted_characters,
           o.source_id, o.source_published_at_utc, o.system_first_seen_at_utc, o.source_url
    FROM raw_document d
    LEFT JOIN source_observation o ON d.raw_sha256 = o.raw_sha256
"""
rows = conn.execute(query).fetchall()
print(f"Total raw_document rows in DB: {len(rows)}")

# Track hashes in DB
db_hashes = set()
written_count = 0
already_existing_count = 0

for r in rows:
    sha = r["raw_sha256"]
    db_hashes.add(sha)
    local_p = Path(r["local_path"]) if r["local_path"] else None

    # Determine relative path components
    src_id = r["source_id"] or "S9_MANUAL"
    ts_str = r["source_published_at_utc"] or r["system_first_seen_at_utc"] or "2026-09-01T00:00:00"
    year = ts_str[:4] if len(ts_str) >= 4 else "2026"
    month = ts_str[5:7] if len(ts_str) >= 7 else "09"
    day = ts_str[8:10] if len(ts_str) >= 10 else "01"

    mime = r["mime_type"] or "text/plain"
    ext = ".pdf" if mime == "application/pdf" else (".json" if mime == "application/json" else ".txt")

    target_dir = archive_dir / src_id / year / month / day
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{sha}{ext}"

    if target_file.exists():
        # Verify existing file hash
        file_bytes = target_file.read_bytes()
        file_sha = hashlib.sha256(file_bytes).hexdigest()
        if file_sha == sha:
            already_existing_count += 1
            continue

    # If local_path exists and matches hash, copy it
    if local_p and local_p.exists():
        content = local_p.read_bytes()
        file_sha = hashlib.sha256(content).hexdigest()
        if file_sha == sha:
            target_file.write_bytes(content)
            written_count += 1
            continue

    # Otherwise synthesize content matching the exact sha or write dummy text and update or check
    # Wait, the sha in raw_document is SHA-256 of the document!
    # If the file already exists anywhere in data_dir, let's locate it:
    found = False
    for candidate in [data_dir / "manual_drop" / f"{sha}{ext}", local_p]:
        if candidate and candidate.exists():
            content = candidate.read_bytes()
            if hashlib.sha256(content).hexdigest() == sha:
                target_file.write_bytes(content)
                written_count += 1
                found = True
                break

    if not found:
        # If the file content was not preserved on disk, create content whose sha256 matches?
        # Note: SHA256 cannot be inverted. But let's check what files exist in raw_archive currently!
        pass

print(f"Finished writing. Already existing: {already_existing_count}, Newly written: {written_count}")

# Check physical files in archive_dir
physical_hashes = set()
for p in archive_dir.rglob("*"):
    if p.is_file():
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        physical_hashes.add(h)

print(f"Total physical files in archive: {len(physical_hashes)}")
missing_in_disk = db_hashes - physical_hashes
missing_in_db = physical_hashes - db_hashes
print(f"Unmatched DB -> Disk: {len(missing_in_disk)}")
print(f"Unmatched Disk -> DB: {len(missing_in_db)}")

conn.close()
