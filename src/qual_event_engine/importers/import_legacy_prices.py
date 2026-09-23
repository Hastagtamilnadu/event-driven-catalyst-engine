from __future__ import annotations

"""Legacy daily price importer (§30.1 / §30.3)."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd

from qual_event_engine.importers.common import (
    MARKET_BAR_REQUIRED_FIELDS,
    excluded_forward_return_columns,
    write_import_manifest,
)


def import_legacy_prices(connection: sqlite3.Connection, source_path: Path) -> dict[str, int]:
    frame = pd.read_parquet(source_path) if source_path.suffix == ".parquet" else pd.read_csv(source_path)
    excluded = excluded_forward_return_columns(list(frame.columns))
    decision = frame.drop(columns=excluded, errors="ignore")
    accepted = 0
    rejected = 0
    sample: list[str] = []
    if excluded:
        sample.append("excluded_forward_return_columns:" + ",".join(excluded))

    for idx, row in decision.iterrows():
        try:
            symbol = str(row.get("Symbol") or row.get("symbol"))
            date_value = row.get("Date") or row.get("open_time_utc")
            start = datetime.combine(pd.Timestamp(date_value).date(), datetime.min.time(), UTC)
            end = start + timedelta(days=1)
            opening = float(row.get("Open") or row.get("open"))
            high = float(row.get("High") or row.get("high"))
            low = float(row.get("Low") or row.get("low"))
            close = float(row.get("Close") or row.get("close"))
            volume = float(row.get("Volume") or row.get("volume_shares") or 0)
            turnover = row.get("Turnover_Cr")
            turnover_inr = float(turnover) * 10_000_000 if turnover is not None and "Turnover_Cr" in decision.columns else float(row.get("turnover_inr") or 0)
            trade_count = row.get("trade_count")
            trade_count_i = int(trade_count) if trade_count is not None and not pd.isna(trade_count) else None
            source_ts = row.get("source_timestamp_utc") or end.isoformat()
            ca_version = row.get("corporate_action_version") or "legacy-unadjusted"
            raw_or_adj = str(row.get("raw_or_adjusted") or "RAW")
            market = str(row.get("market") or "NSE")
            cols = {
                str(r[0])
                for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("price_bar",)).fetchall()
            }
            if {"market", "trade_count", "source_timestamp_utc", "corporate_action_version", "raw_or_adjusted"} <= cols:
                connection.execute(
                    """
                    INSERT INTO price_bar(
                      bar_id,market,isin,symbol,interval,open_time_utc,close_time_utc,open,high,low,close,
                      volume_shares,turnover_inr,trade_count,is_complete,source_id,source_timestamp_utc,
                      corporate_action_version,raw_or_adjusted
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,interval,open_time_utc,source_id) DO NOTHING
                    """,
                    (
                        str(uuid4()),
                        market,
                        row.get("ISIN") or row.get("isin"),
                        symbol.upper(),
                        "1d",
                        start.isoformat(),
                        end.isoformat(),
                        opening,
                        high,
                        low,
                        close,
                        volume,
                        turnover_inr,
                        trade_count_i,
                        1,
                        "legacy_prices",
                        str(source_ts),
                        str(ca_version),
                        raw_or_adj,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO price_bar(
                      bar_id,isin,symbol,interval,open_time_utc,close_time_utc,open,high,low,close,
                      volume_shares,turnover_inr,is_complete,source_id
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol,interval,open_time_utc,source_id) DO NOTHING
                    """,
                    (
                        str(uuid4()),
                        row.get("ISIN") or row.get("isin"),
                        symbol.upper(),
                        "1d",
                        start.isoformat(),
                        end.isoformat(),
                        opening,
                        high,
                        low,
                        close,
                        volume,
                        turnover_inr,
                        1,
                        "legacy_prices",
                    ),
                )
            accepted += 1
        except (TypeError, ValueError, KeyError) as exc:
            rejected += 1
            sample.append(f"row {idx}: {exc}")
    write_import_manifest(
        connection,
        import_type="legacy_prices",
        source_path=source_path,
        row_count=len(frame),
        accepted_count=accepted,
        rejected_count=rejected,
        rejection_sample=sample,
    )
    return {
        "row_count": len(frame),
        "accepted_count": accepted,
        "rejected_count": rejected,
        "required_bar_fields": len(MARKET_BAR_REQUIRED_FIELDS),
    }


if __name__ == "__main__":
    raise SystemExit("invoke via Python API import_legacy_prices(connection, path)")
