from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class USFDAStrategy(BaseStrategy):
    """FD-01: USFDA Inspection Classifications & Form 483 Clearances (§13.4)."""

    strategy_id = "FD-01"
    name = "USFDA Approvals & Clearances"
    event_types: ClassVar[list[str]] = ["USFDA_FINAL_CLASSIFICATION"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") != "USFDA_FINAL_CLASSIFICATION":
            return None
        if assessment.recommendation != "BUY_CANDIDATE":
            return None
        if int(event.get("firmness_level", 0)) < 4:
            return None

        headline = (event.get("headline") or "").upper()
        # NAI (No Action Indicated) or VAI (Voluntary Action Indicated) without Warning Letter
        is_favorable = "NAI" in headline or "CLEARANCE" in headline or "CLOSED" in headline
        if not is_favorable:
            return None

        conviction = 0.8 if "NAI" in headline else 0.6

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="BUY",
            conviction_score=conviction,
            holding_sessions=5,
            stop_loss_pct=6.0,
            target_pct=12.0,
            rationale=f"Favorable USFDA EIR clearance ({headline})",
        )
