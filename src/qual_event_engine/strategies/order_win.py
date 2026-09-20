from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.normalization.algorithms import calculate_materiality_ratio
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class OrderWinStrategy(BaseStrategy):
    """OR-01: Commercial Order Wins with Backlog Impact (§13.3)."""

    strategy_id = "OR-01"
    name = "Commercial Order Wins"
    event_types: ClassVar[list[str]] = ["ORDER_WIN"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") != "ORDER_WIN":
            return None
        if assessment.recommendation != "BUY_CANDIDATE":
            return None
        if int(event.get("firmness_level", 0)) < 4:
            return None

        event_val = float(event.get("event_value_inr") or 0.0)
        ttm_rev = float(event.get("ttm_revenue_inr") or 0.0)
        mat_ratio, _ = calculate_materiality_ratio(
            order_value_inr=event_val,
            ttm_revenue_inr=ttm_rev if ttm_rev > 0 else None,
        )

        # Minimum materiality threshold 15% (or ratio >= 0.15)
        if mat_ratio < 0.15 and event_val < 500_000_000:  # < 50 Cr without materiality
            return None

        conviction = min(1.0, 0.6 + (mat_ratio * 0.2))

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="BUY",
            conviction_score=conviction,
            holding_sessions=20,
            stop_loss_pct=6.0,
            target_pct=20.0,
            rationale=f"Commercial order win of INR {event_val:,.0f} (Materiality: {mat_ratio:.1%})",
        )
