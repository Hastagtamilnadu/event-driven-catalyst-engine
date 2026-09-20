from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class GovernanceStrategy(BaseStrategy):
    """GV-01: Governance Penalties, Forensic Audits & Auditor Resignations (Negative Overlay) (§13.5)."""

    strategy_id = "GV-01"
    name = "Governance Negative Overlay"
    event_types: ClassVar[list[str]] = ["NEGATIVE_GOVERNANCE", "USFDA_WARNING_LETTER"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") not in self.event_types:
            return None

        # Negative governance events trigger immediate exit/liquidation of any existing position
        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="SELL",  # Liquidation signal
            conviction_score=1.0,
            holding_sessions=0,  # Immediate exit
            stop_loss_pct=0.0,
            target_pct=None,
            rationale=f"Negative governance event detected: {event.get('headline')}",
        )
