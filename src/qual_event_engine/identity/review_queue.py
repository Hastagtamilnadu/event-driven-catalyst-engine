from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class IdentityReviewItem:
    item_id: str
    raw_name: str
    candidate_isin: str | None
    candidate_symbol: str | None
    candidate_name: str | None
    confidence: float
    match_method: str
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    created_at_utc: datetime
    decided_at_utc: datetime | None = None
    reviewer_notes: str | None = None


class IdentityReviewQueue:
    """Manages manual human review for low-confidence or ambiguous entity resolutions."""

    def __init__(self) -> None:
        self._queue: dict[str, IdentityReviewItem] = {}

    def enqueue(
        self,
        item_id: str,
        raw_name: str,
        candidate_isin: str | None,
        candidate_symbol: str | None,
        candidate_name: str | None,
        confidence: float,
        match_method: str,
    ) -> IdentityReviewItem:
        item = IdentityReviewItem(
            item_id=item_id,
            raw_name=raw_name,
            candidate_isin=candidate_isin,
            candidate_symbol=candidate_symbol,
            candidate_name=candidate_name,
            confidence=confidence,
            match_method=match_method,
            status="PENDING",
            created_at_utc=datetime.now(UTC),
        )
        self._queue[item_id] = item
        return item

    def get_pending(self) -> list[IdentityReviewItem]:
        return [item for item in self._queue.values() if item.status == "PENDING"]

    def approve(self, item_id: str, notes: str = "") -> IdentityReviewItem:
        if item_id not in self._queue:
            raise KeyError(f"Item {item_id} not found")
        old = self._queue[item_id]
        updated = IdentityReviewItem(
            item_id=old.item_id,
            raw_name=old.raw_name,
            candidate_isin=old.candidate_isin,
            candidate_symbol=old.candidate_symbol,
            candidate_name=old.candidate_name,
            confidence=1.0,
            match_method="MANUAL_APPROVAL",
            status="APPROVED",
            created_at_utc=old.created_at_utc,
            decided_at_utc=datetime.now(UTC),
            reviewer_notes=notes,
        )
        self._queue[item_id] = updated
        return updated

    def reject(self, item_id: str, notes: str = "") -> IdentityReviewItem:
        if item_id not in self._queue:
            raise KeyError(f"Item {item_id} not found")
        old = self._queue[item_id]
        updated = IdentityReviewItem(
            item_id=old.item_id,
            raw_name=old.raw_name,
            candidate_isin=old.candidate_isin,
            candidate_symbol=old.candidate_symbol,
            candidate_name=old.candidate_name,
            confidence=0.0,
            match_method="MANUAL_REJECTION",
            status="REJECTED",
            created_at_utc=old.created_at_utc,
            decided_at_utc=datetime.now(UTC),
            reviewer_notes=notes,
        )
        self._queue[item_id] = updated
        return updated
