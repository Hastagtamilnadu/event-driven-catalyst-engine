from __future__ import annotations

"""Shared §30 import-manifest writer."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from qual_event_engine.operations.hashing import sha256_file

COLUMN_MAPPING_VERSION = "30.1-v1"

FORWARD_RETURN_COLUMNS = frozenset(
    {
        "fwd_ret_1d",
        "fwd_ret_5d",
        "fwd_ret_10d",
        "fwd_ret_20d",
        "forward_return",
        "forward_return_1d",
        "forward_return_5d",
        "t1_return",
        "t5_return",
        "t20_return",
        "next_day_return",
        "cum_fwd_return",
    }
)

MARKET_BAR_REQUIRED_FIELDS = (
    "market",
    "isin",
    "symbol",
    "interval",
    "open_time_utc",
    "close_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume_shares",
    "turnover_inr",
    "trade_count",
    "is_complete",
    "source_id",
    "source_timestamp_utc",
    "corporate_action_version",
    "raw_or_adjusted",
)


def excluded_forward_return_columns(columns: list[str]) -> list[str]:
    lower = {c.lower(): c for c in columns}
    hit = []
    for name in FORWARD_RETURN_COLUMNS:
        if name.lower() in lower:
            hit.append(lower[name.lower()])
    return hit


def write_import_manifest(
    connection: sqlite3.Connection,
    *,
    import_type: str,
    source_path: Path,
    row_count: int,
    accepted_count: int,
    rejected_count: int,
    rejection_sample: list[str],
    column_mapping_version: str = COLUMN_MAPPING_VERSION,
) -> str:
    import_id = str(uuid4())
    source_hash = sha256_file(source_path) if source_path.exists() else "missing"
    import_time = datetime.now(UTC).isoformat()
    cols = {
        str(r[0])
        for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("import_manifest",)).fetchall()
    }
    notes = json.dumps(
        {
            "source_path": str(source_path),
            "source_hash": source_hash,
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "column_mapping_version": column_mapping_version,
            "import_time": import_time,
            "rejection_sample": rejection_sample[:20],
        },
        default=str,
    )
    if {"source_path", "source_hash", "accepted_count", "rejected_count"} <= cols:
        connection.execute(
            """
            INSERT INTO import_manifest(
              import_id, import_type, source_file, imported_at_utc, row_count, checksum_sha256, status, notes,
              source_path, source_hash, accepted_count, rejected_count, column_mapping_version, import_time, rejection_sample
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                import_id,
                import_type,
                str(source_path),
                import_time,
                row_count,
                source_hash,
                "COMPLETE" if rejected_count == 0 else "PARTIAL",
                notes,
                str(source_path),
                source_hash,
                accepted_count,
                rejected_count,
                column_mapping_version,
                import_time,
                json.dumps(rejection_sample[:20]),
            ),
        )
    else:
        connection.execute(
            """
            INSERT INTO import_manifest(
              import_id, import_type, source_file, imported_at_utc, row_count, checksum_sha256, status, notes
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                import_id,
                import_type,
                str(source_path),
                import_time,
                row_count,
                source_hash,
                "COMPLETE" if rejected_count == 0 else "PARTIAL",
                notes,
            ),
        )
    return import_id
