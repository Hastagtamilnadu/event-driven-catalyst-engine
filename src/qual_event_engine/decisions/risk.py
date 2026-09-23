from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def _as_utc(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(UTC).isoformat()


def _is_source_outage_only(service: str) -> bool:
    return service == "SOURCE_OUTAGE" or service.startswith("SOURCE_OUTAGE")


def _observation_id_for_event(connection: sqlite3.Connection, event: sqlite3.Row) -> str | None:
    keys = set(event.keys())
    if "observation_id" in keys and event["observation_id"]:
        return str(event["observation_id"])
    row = connection.execute(
        """SELECT observation_id FROM event_revision
           WHERE event_id=? ORDER BY revision_number DESC LIMIT 1""",
        (event["event_id"],),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def entry_gate(connection: sqlite3.Connection, event: sqlite3.Row) -> tuple[bool, str]:
    incidents = connection.execute(
        "SELECT service, summary FROM incident WHERE status='OPEN'"
    ).fetchall()
    global_incident = any(not _is_source_outage_only(str(row["service"] or "")) for row in incidents)
    if global_incident:
        return False, "OPEN_INCIDENT"
    observation_id = _observation_id_for_event(connection, event)
    if not observation_id:
        return False, "MISSING_OBSERVATION"
    obs = connection.execute(
        """SELECT source_published_at_utc FROM source_observation
           WHERE observation_id=?""",
        (observation_id,),
    ).fetchone()
    if not obs or not obs["source_published_at_utc"]:
        return False, "MISSING_OBSERVATION"
    decision_time = _as_utc(obs["source_published_at_utc"])
    membership = connection.execute(
        """SELECT * FROM security_membership
           WHERE symbol=? AND effective_from_utc<=?
             AND (effective_to_utc IS NULL OR effective_to_utc>?)
           ORDER BY effective_from_utc DESC LIMIT 1""",
        (event["symbol"], decision_time, decision_time),
    ).fetchone()
    if not membership:
        return False, "MISSING_POINT_IN_TIME_UNIVERSE"
    if membership["series"] != "EQ" or not bool(membership["eligible"]):
        return False, "UNIVERSE_INELIGIBLE"
    if membership["surveillance_status"] not in {"NONE", "NORMAL"}:
        return False, "SURVEILLANCE_RESTRICTED"
    band = membership["price_band_pct"]
    if band is not None and float(band) <= 5.0:
        return False, "PRICE_BAND_RESTRICTED"
    blacklist = connection.execute(
        """SELECT 1 FROM blacklist WHERE symbol=? AND status='ACTIVE'
           AND starts_at_utc<=? AND ends_at_utc>? LIMIT 1""",
        (event["symbol"], decision_time, decision_time),
    ).fetchone()
    if blacklist:
        return False, "NEGATIVE_EVENT_BLACKLIST"
    return True, "OK"


def apply_negative_overlay(
    connection: sqlite3.Connection, event_id: str, symbol: str, sessions: int
) -> None:
    now = datetime.now(UTC)
    ends = now + timedelta(days=max(1, sessions) * 2)
    connection.execute(
        """INSERT INTO blacklist(blacklist_id,symbol,reason_event_id,starts_at_utc,ends_at_utc,status)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(symbol,reason_event_id) DO NOTHING""",
        (str(uuid4()), symbol, event_id, now.isoformat(), ends.isoformat(), "ACTIVE"),
    )
    lots = connection.execute(
        """SELECT * FROM position_lot WHERE symbol=? AND status='OPEN'""", (symbol,)
    ).fetchall()
    for lot in lots:
        already_requested = connection.execute(
            """SELECT 1 FROM paper_order
               WHERE strategy_id=? AND symbol=? AND side='SELL'
                 AND status IN ('PENDING_EXIT','PENDING_PRICE')""",
            (lot["strategy_id"], symbol),
        ).fetchone()
        if already_requested:
            continue
        order_cols = {
            str(r[0])
            for r in connection.execute(
                "SELECT name FROM pragma_table_info(?)", ("paper_order",)
            ).fetchall()
        }
        insert_cols = [
            "paper_order_id",
            "client_order_id",
            "event_id",
            "strategy_id",
            "strategy_version",
            "symbol",
            "isin",
            "side",
            "quantity_requested",
            "order_type",
            "limit_price",
            "trigger_price",
            "participation_cap",
            "valid_from_utc",
            "valid_until_utc",
            "status",
            "decision_snapshot_hash",
            "created_at_utc",
        ]
        values: list[object] = [
            str(uuid4()),
            f"{lot['position_lot_id']}:NEGATIVE:{event_id}",
            event_id,
            lot["strategy_id"],
            "1",
            symbol,
            lot["isin"],
            "SELL",
            lot["quantity_open"],
            "PAPER_MARKET",
            None,
            None,
            1.0,
            now.isoformat(),
            (now + timedelta(days=5)).isoformat(),
            "PENDING_EXIT",
            event_id,
            now.isoformat(),
        ]
        if "quantity_remaining" in order_cols:
            insert_cols.insert(9, "quantity_remaining")
            values.insert(9, lot["quantity_open"])
        if "participation_cap" not in order_cols and "participation_cap_pct" in order_cols:
            insert_cols[insert_cols.index("participation_cap")] = "participation_cap_pct"
        placeholders = ",".join("?" for _ in insert_cols)
        connection.execute(
            "INSERT INTO paper_order(" + ",".join(insert_cols) + ") VALUES(" + placeholders + ")",
            values,
        )
