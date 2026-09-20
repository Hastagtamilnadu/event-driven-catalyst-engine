from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EventRevisionRecord:
    revision_id: str
    event_id: str
    revision_number: int
    revised_at_utc: datetime
    field_name: str
    old_value: str | None
    new_value: str | None
    reason: str


class RevisionManager:
    """Tracks updates, corrections, and revisions to canonical events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def record_revision(
        self,
        event_id: str,
        field_name: str,
        old_value: str | None,
        new_value: str | None,
        reason: str,
    ) -> EventRevisionRecord:
        cursor = self.connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM event_revision WHERE event_id = ?",
            (event_id,),
        )
        next_rev = int(cursor.fetchone()[0])

        rev_id = str(uuid4())
        now = datetime.now(UTC)

        self.connection.execute(
            """
            INSERT INTO event_revision (
                revision_id, event_id, revision_number, revised_at_utc,
                field_name, old_value, new_value, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rev_id,
                event_id,
                next_rev,
                now.isoformat(),
                field_name,
                old_value,
                new_value,
                reason,
            ),
        )

        return EventRevisionRecord(
            revision_id=rev_id,
            event_id=event_id,
            revision_number=next_rev,
            revised_at_utc=now,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
        )

    def get_revisions(self, event_id: str) -> list[EventRevisionRecord]:
        cursor = self.connection.execute(
            """
            SELECT revision_id, event_id, revision_number, revised_at_utc,
                   field_name, old_value, new_value, reason
            FROM event_revision
            WHERE event_id = ?
            ORDER BY revision_number ASC
            """,
            (event_id,),
        )
        rows = cursor.fetchall()
        return [
            EventRevisionRecord(
                revision_id=r[0],
                event_id=r[1],
                revision_number=r[2],
                revised_at_utc=datetime.fromisoformat(r[3]),
                field_name=r[4],
                old_value=r[5],
                new_value=r[6],
                reason=r[7],
            )
            for r in rows
        ]
