from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class CalendarStrategy(BaseStrategy):
    """CL-01: Corporate Calendar & Earnings Pre-Announcements (§13.6)."""

    strategy_id = "CL-01"
    name = "Corporate Calendar Pre-Announcements"
    event_types: ClassVar[list[str]] = ["CALENDAR_EVENT"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") != "CALENDAR_EVENT":
            return None
        if assessment.recommendation != "BUY_CANDIDATE":
            return None
        if int(event.get("firmness_level", 0)) < 4:
            return None

        headline = (event.get("headline") or "").lower()
        is_pre_announcement = "earlier" in headline or "pre-announcement" in headline or "advancement" in headline
        if not is_pre_announcement:
            return None

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="BUY",
            conviction_score=0.6,
            holding_sessions=10,
            stop_loss_pct=6.0,
            target_pct=10.0,
            rationale=f"Favorable calendar pre-announcement: {event.get('headline')}",
        )
