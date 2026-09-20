from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class DecisionReviewItem:
    review_id: str
    event_id: str
    symbol: str
    strategy_id: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
    rationale: str
    created_at_utc: datetime
    decided_at_utc: datetime | None = None
    decision_reason: str | None = None


class DecisionReviewer:
    """Manages the human-in-the-loop review queue for trading intents."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_pending_reviews(self) -> list[DecisionReviewItem]:
        query = """
            SELECT r.review_id, r.event_id, e.symbol, r.strategy_id, r.status,
                   r.rationale, r.created_at_utc
            FROM decision_review_queue r
            JOIN canonical_event e ON r.event_id = e.event_id
            WHERE r.status = 'PENDING'
            ORDER BY r.created_at_utc ASC
        """
        try:
            cur = self.connection.execute(query)
            rows = cur.fetchall()
            return [
                DecisionReviewItem(
                    review_id=str(r[0]),
                    event_id=str(r[1]),
                    symbol=str(r[2]),
                    strategy_id=str(r[3]),
                    status=r[4],
                    rationale=str(r[5] or ""),
                    created_at_utc=datetime.fromisoformat(r[6]),
                )
                for r in rows
            ]
        except sqlite3.OperationalError:
            return []

    def approve_review(self, review_id: str, reason: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE decision_review_queue
            SET status = 'APPROVED', decided_at_utc = ?, decision_reason = ?
            WHERE review_id = ?
            """,
            (now, reason, review_id),
        )

    def reject_review(self, review_id: str, reason: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE decision_review_queue
            SET status = 'REJECTED', decided_at_utc = ?, decision_reason = ?
            WHERE review_id = ?
            """,
            (now, reason, review_id),
        )
