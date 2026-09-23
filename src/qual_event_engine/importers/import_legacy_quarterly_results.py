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


def import_legacy_quarterly_results(connection: sqlite3.Connection, source_path: Path) -> dict[str, int]:
    frame = pd.read_parquet(source_path) if source_path.suffix == ".parquet" else pd.read_csv(source_path)
    excluded = excluded_forward_return_columns(list(frame.columns))
    decision = frame.drop(columns=excluded, errors="ignore")
    accepted = 0
    rejected = 0
    sample: list[str] = [f"excluded:{','.join(excluded)}"] if excluded else []
    now = datetime.now(UTC).isoformat()
    metric_map = {
        "Revenue": "REVENUE_INR",
        "revenue": "REVENUE_INR",
        "PAT": "PAT_INR",
        "NetProfit": "PAT_INR",
        "EBITDA": "EBITDA_INR",
        "CFO": "CFO_INR",
        "Receivables": "RECEIVABLES_INR",
    }
    for idx, row in decision.iterrows():
        try:
            symbol = str(row.get("Symbol") or row.get("symbol"))
            period = str(row.get("period_end") or row.get("Quarter") or row.get("Date") or "")
            for src_col, metric in metric_map.items():
                if src_col not in decision.columns or pd.isna(row.get(src_col)):
                    continue
                connection.execute(
                    """
                    INSERT INTO point_in_time_fundamental(
                      fundamental_id,isin,symbol,metric,value,period_end,issuer_disseminated_at_utc,
                      system_first_seen_at_utc,eligible_at_utc,source_id,source_version
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid4()),
                        row.get("ISIN") or row.get("isin"),
                        symbol.upper(),
                        metric,
                        float(row[src_col]),
                        period,
                        now,
                        now,
                        now,
                        "legacy_quarterly",
                        "30.1-v1",
                    ),
                )
                accepted += 1
        except (TypeError, ValueError, KeyError, sqlite3.IntegrityError) as exc:
            rejected += 1
            sample.append(f"row {idx}: {exc}")
    write_import_manifest(
        connection,
        import_type="legacy_quarterly_results",
        source_path=source_path,
        row_count=len(frame),
        accepted_count=accepted,
        rejected_count=rejected,
        rejection_sample=sample,
    )
    return {"row_count": len(frame), "accepted_count": accepted, "rejected_count": rejected}
