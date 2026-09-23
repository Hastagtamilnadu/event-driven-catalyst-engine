from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from qual_event_engine.importers.common import write_import_manifest


def import_legacy_raw_archive(connection: sqlite3.Connection, source_path: Path) -> dict[str, int]:
    files = [source_path] if source_path.is_file() else sorted(p for p in source_path.rglob("*") if p.is_file())
    accepted = 0
    rejected = 0
    sample: list[str] = []
    now = datetime.now(UTC).isoformat()
    for path in files:
        try:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            connection.execute(
                """
                INSERT INTO raw_document(
                  raw_sha256, local_path, mime_type, bytes, page_count, extracted_characters,
                  extraction_quality, archived_at_utc, malware_scan_status, parser_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(raw_sha256) DO NOTHING
                """,
                (
                    digest,
                    str(path),
                    "application/octet-stream",
                    len(data),
                    None,
                    0,
                    "UNSUPPORTED",
                    now,
                    "NOT_SCANNED",
                    "IMPORTED",
                ),
            )
            accepted += 1
        except (OSError, sqlite3.IntegrityError) as exc:
            rejected += 1
            sample.append(f"{path}: {exc}")
    write_import_manifest(
        connection,
        import_type="legacy_raw_archive",
        source_path=source_path,
        row_count=len(files),
        accepted_count=accepted,
        rejected_count=rejected,
        rejection_sample=sample,
    )
    return {"row_count": len(files), "accepted_count": accepted, "rejected_count": rejected}
