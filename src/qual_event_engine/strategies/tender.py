from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class TenderStrategy(BaseStrategy):
    """TN-01: Government & PSU Tenders and Contract Execution (§13.2)."""

    strategy_id = "TN-01"
    name = "Government & PSU Tenders"
    event_types: ClassVar[list[str]] = ["EXECUTED_CONTRACT"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") != "EXECUTED_CONTRACT":
            return None
        if assessment.recommendation != "BUY_CANDIDATE":
            return None
        if int(event.get("firmness_level", 0)) < 4:
            return None

        # Materiality ratio check
        mat_ratio = float(event.get("materiality_ratio") or 0.0)
        conviction = 0.7 if mat_ratio >= 0.15 else 0.5

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="BUY",
            conviction_score=conviction,
            holding_sessions=20,
            stop_loss_pct=6.0,
            target_pct=18.0,
            rationale=f"Executed government contract with firmness {event.get('firmness_level')}",
        )
