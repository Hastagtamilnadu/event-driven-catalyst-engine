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


def import_legacy_universe(connection: sqlite3.Connection, source_path: Path) -> dict[str, int]:
    frame = pd.read_csv(source_path) if source_path.suffix.lower() == ".csv" else pd.read_parquet(source_path)
    excluded = excluded_forward_return_columns(list(frame.columns))
    decision = frame.drop(columns=excluded, errors="ignore")
    accepted = 0
    rejected = 0
    sample: list[str] = []
    now = datetime.now(UTC).isoformat()
    for idx, row in decision.iterrows():
        try:
            symbol = str(row.get("Symbol") or row.get("symbol") or row.get("SYMBOL"))
            connection.execute(
                """
                INSERT INTO security_membership(
                  membership_id,isin,symbol,legal_name,effective_from_utc,effective_to_utc,series,
                  listed_status,surveillance_status,price_band_pct,market_cap_inr,adv20_shares,adt20_inr,
                  eligible,eligibility_reasons,source_id,source_version
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid4()),
                    row.get("ISIN") or row.get("isin"),
                    symbol.upper(),
                    str(row.get("legal_name") or row.get("Company") or symbol),
                    now,
                    None,
                    str(row.get("series") or "EQ"),
                    str(row.get("listed_status") or "LISTED"),
                    str(row.get("surveillance_status") or "NONE"),
                    float(row["price_band_pct"]) if row.get("price_band_pct") is not None else 10.0,
                    None,
                    None,
                    None,
                    1,
                    "legacy_universe_import",
                    "legacy_universe",
                    "30.1-v1",
                ),
            )
            accepted += 1
        except (TypeError, ValueError, KeyError, sqlite3.IntegrityError) as exc:
            rejected += 1
            sample.append(f"row {idx}: {exc}")
    write_import_manifest(
        connection,
        import_type="legacy_universe",
        source_path=source_path,
        row_count=len(frame),
        accepted_count=accepted,
        rejected_count=rejected,
        rejection_sample=sample,
    )
    return {"row_count": len(frame), "accepted_count": accepted, "rejected_count": rejected}
