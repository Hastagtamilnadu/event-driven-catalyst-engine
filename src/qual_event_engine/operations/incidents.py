from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from qual_event_engine.operations.health import open_incident


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    incident_id: str
    severity: str  # P1, P2, P3
    service: str
    summary: str
    opened_at_utc: datetime
    resolved_at_utc: datetime | None
    status: str  # OPEN, RESOLVED
    resolution_notes: str | None = None


class IncidentManager:
    """Manages operational incidents and trading freeze triggers."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def trigger_incident(self, severity: str, service: str, summary: str) -> str:
        return open_incident(self.connection, severity, service, summary)

    def is_system_frozen(self) -> bool:
        cur = self.connection.execute("SELECT 1 FROM incident WHERE status = 'OPEN' LIMIT 1")
        return cur.fetchone() is not None

    def resolve_incident(self, incident_id: str, resolution_notes: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE incident
            SET status = 'RESOLVED', resolved_at_utc = ?, resolution_notes = ?
            WHERE incident_id = ?
            """,
            (now, resolution_notes, incident_id),
        )
