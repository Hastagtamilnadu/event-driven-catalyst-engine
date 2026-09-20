from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class DuplicateCheckResult:
    is_duplicate: bool
    canonical_event_id: str | None
    similarity_score: float
    reason: str


class EventDeduplicator:
    """Deduplicates incoming qualitative events across multiple feeds and time horizons."""

    def __init__(self, connection: sqlite3.Connection, window_hours: int = 72) -> None:
        self.connection = connection
        self.window_hours = window_hours

    def check_duplicate(
        self,
        symbol: str,
        event_type: str,
        event_time_utc: datetime,
        event_value_inr: float | None = None,
        headline: str = "",
    ) -> DuplicateCheckResult:
        window_start = (event_time_utc - timedelta(hours=self.window_hours)).isoformat()
        window_end = (event_time_utc + timedelta(hours=self.window_hours)).isoformat()

        cursor = self.connection.execute(
            """
            SELECT event_id, event_value_inr, headline, event_occurred_at_utc
            FROM canonical_event
            WHERE symbol = ? AND event_type = ?
              AND event_occurred_at_utc BETWEEN ? AND ?
            ORDER BY event_occurred_at_utc ASC
            """,
            (symbol.upper(), event_type, window_start, window_end),
        )
        rows = cursor.fetchall()
        if not rows:
            return DuplicateCheckResult(
                is_duplicate=False,
                canonical_event_id=None,
                similarity_score=0.0,
                reason="NO_MATCHING_EVENT_IN_WINDOW",
            )

        for r in rows:
            event_id = str(r[0])
            ex_val = r[1]
            ex_head = str(r[2] or "")

            # If both have contract values, compare them
            if event_value_inr is not None and ex_val is not None and abs(event_value_inr - float(ex_val)) / max(event_value_inr, float(ex_val), 1.0) < 0.05:
                return DuplicateCheckResult(
                    is_duplicate=True,
                        canonical_event_id=event_id,
                        similarity_score=0.95,
                        reason="MATCHING_SYMBOL_TYPE_VALUE_IN_WINDOW",
                    )

            # Check headline similarity
            head_clean = headline.upper().strip()
            ex_head_clean = ex_head.upper().strip()
            if head_clean and ex_head_clean and head_clean == ex_head_clean:
                return DuplicateCheckResult(
                    is_duplicate=True,
                    canonical_event_id=event_id,
                    similarity_score=1.0,
                    reason="EXACT_HEADLINE_MATCH_IN_WINDOW",
                )

        # Fallback to closest match in window
        return DuplicateCheckResult(
            is_duplicate=True,
            canonical_event_id=str(rows[0][0]),
            similarity_score=0.80,
            reason="MATCHING_SYMBOL_AND_TYPE_IN_WINDOW",
        )
