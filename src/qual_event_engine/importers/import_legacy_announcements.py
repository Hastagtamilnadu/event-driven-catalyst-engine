from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from qual_event_engine.importers.common import (
    excluded_forward_return_columns,
    write_import_manifest,
)


def import_legacy_announcements(connection: sqlite3.Connection, source_path: Path) -> dict[str, int]:
    frame = pd.read_parquet(source_path) if source_path.suffix == ".parquet" else pd.read_csv(source_path)
    excluded = excluded_forward_return_columns(list(frame.columns))
    decision = frame.drop(columns=excluded, errors="ignore")
    accepted = 0
    rejected = 0
    sample: list[str] = [f"excluded:{','.join(excluded)}"] if excluded else []
    now = datetime.now(UTC).isoformat()
    for idx, row in decision.iterrows():
        try:
            obs_id = str(uuid4())
            event_id = str(uuid4())
            native = str(row.get("source_native_id") or row.get("id") or idx)
            url = str(row.get("source_url") or row.get("url") or "https://legacy.local/announcement")
            published = str(row.get("source_published_at_utc") or row.get("Date") or now)
            job_id = "legacy-import"
            connection.execute(
                """
                INSERT OR IGNORE INTO job_run(job_run_id, job_name, started_at_utc, status, config_hash, code_version)
                VALUES(?,?,?,?,?,?)
                """,
                (job_id, "legacy_announcements", now, "STARTED", "legacy", "30.1-v1"),
            )
            connection.execute(
                """
                INSERT INTO source_observation(
                  observation_id,source_id,source_native_id,source_url,source_published_at_utc,
                  system_first_seen_at_utc,raw_sha256,retrieval_status,job_run_id
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (obs_id, "S1_EXCHANGE", native, url, str(published), now, "legacy-pending", "IMPORTED", job_id),
            )
            connection.execute(
                """
                INSERT INTO canonical_event(
                  event_id,entity_id,isin,symbol,event_type,event_status,event_occurred_at_utc,
                  decision_eligible_at_utc,entity_match_status,event_state,created_at_utc,latest_revision_number
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    None,
                    row.get("ISIN") or row.get("isin"),
                    str(row.get("Symbol") or row.get("symbol") or "UNKNOWN"),
                    str(row.get("event_type") or "POLICY_EVENT"),
                    "IMPORTED",
                    str(published),
                    None,
                    "UNRESOLVED",
                    "INGESTED",
                    now,
                    1,
                ),
            )
            accepted += 1
        except (TypeError, ValueError, KeyError, sqlite3.IntegrityError) as exc:
            rejected += 1
            sample.append(f"row {idx}: {exc}")
    write_import_manifest(
        connection,
        import_type="legacy_announcements",
        source_path=source_path,
        row_count=len(frame),
        accepted_count=accepted,
        rejected_count=rejected,
        rejection_sample=sample,
    )
    return {"row_count": len(frame), "accepted_count": accepted, "rejected_count": rejected}
