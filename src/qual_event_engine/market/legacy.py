from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd


def import_daily_turnover_parquet(
    connection: sqlite3.Connection, path: Path, source_id: str = "legacy_daily_turnover"
) -> int:
    """Import daily bars. These bars are explicitly daily and cannot trigger intraday fills."""

    frame = pd.read_parquet(path)
    required = ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "Turnover_Cr"]
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"Legacy daily bars missing columns: {sorted(missing)}")
    rows: list[tuple[object, ...]] = []
    for row in frame.loc[:, required].itertuples(index=False):
        date_value, symbol, opening, high, low, close, volume, turnover_cr = row
        start = datetime.combine(pd.Timestamp(date_value).date(), datetime.min.time(), UTC)
        end = start + timedelta(days=1)
        rows.append(
            (
                str(uuid4()),
                None,
                str(symbol).upper(),
                "1d",
                start.isoformat(),
                end.isoformat(),
                float(opening),
                float(high),
                float(low),
                float(close),
                float(volume),
                float(turnover_cr) * 10_000_000,
                1,
                source_id,
            )
        )
        if len(rows) >= 10_000:
            _insert_rows(connection, rows)
            rows.clear()
    if rows:
        _insert_rows(connection, rows)
    return len(frame)


def _insert_rows(connection: sqlite3.Connection, rows: list[tuple[object, ...]]) -> None:
    connection.executemany(
        """INSERT INTO price_bar(
          bar_id,isin,symbol,interval,open_time_utc,close_time_utc,open,high,low,close,
          volume_shares,turnover_inr,is_complete,source_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(symbol,interval,open_time_utc,source_id) DO NOTHING""",
        rows,
    )
