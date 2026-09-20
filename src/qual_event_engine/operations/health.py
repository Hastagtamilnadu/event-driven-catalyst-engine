from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4


def health_snapshot(connection: sqlite3.Connection) -> dict[str, object]:
    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    source_rows = connection.execute(
        """SELECT source_id,COUNT(*) AS count,MAX(system_first_seen_at_utc) AS latest
           FROM source_observation GROUP BY source_id ORDER BY source_id"""
    ).fetchall()
    state_rows = connection.execute(
        "SELECT event_state,COUNT(*) AS count FROM canonical_event GROUP BY event_state"
    ).fetchall()
    order_rows = connection.execute(
        "SELECT status,COUNT(*) AS count FROM paper_order GROUP BY status"
    ).fetchall()
    incidents = connection.execute(
        "SELECT severity,service,summary,opened_at_utc FROM incident WHERE status='OPEN' ORDER BY opened_at_utc DESC"
    ).fetchall()
    return {
        "status": "FROZEN" if incidents else "OK",
        "sources": [dict(row) for row in source_rows],
        "event_states": [dict(row) for row in state_rows],
        "order_states": [dict(row) for row in order_rows],
        "open_incidents": [dict(row) for row in incidents],
        "cutoff_utc": cutoff,
    }


def open_incident(connection: sqlite3.Connection, severity: str, service: str, summary: str) -> str:
    incident_id = str(uuid4())
    connection.execute(
        """INSERT INTO incident(incident_id,severity,service,opened_at_utc,status,summary)
           VALUES(?,?,?,?,?,?)""",
        (incident_id, severity, service, datetime.now(UTC).isoformat(), "OPEN", summary),
    )
    return incident_id


def record_source_health(
    connection: sqlite3.Connection, source_id: str, status: str, document_count: int, detail: str
) -> str:
    health_id = str(uuid4())
    connection.execute(
        """INSERT INTO source_health(health_id,source_id,checked_at_utc,status,document_count,detail)
           VALUES(?,?,?,?,?,?)""",
        (
            health_id,
            source_id,
            datetime.now(UTC).isoformat(),
            status,
            document_count,
            detail,
        ),
    )
    return health_id
