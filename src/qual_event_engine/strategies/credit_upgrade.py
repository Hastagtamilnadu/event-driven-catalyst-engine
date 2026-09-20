from __future__ import annotations

from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment
from qual_event_engine.normalization.algorithms import calculate_rating_notch_change
from qual_event_engine.strategies.base import BaseStrategy, StrategySignal


class CreditUpgradeStrategy(BaseStrategy):
    """CR-01: Multi-Notch Credit Rating Upgrades (§13.1)."""

    strategy_id = "CR-01"
    name = "Credit Rating Upgrades"
    event_types: ClassVar[list[str]] = ["CREDIT_UPGRADE"]

    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        if event.get("event_type") != "CREDIT_UPGRADE":
            return None
        if assessment.recommendation != "BUY_CANDIDATE":
            return None
        if int(event.get("firmness_level", 0)) < 4:
            return None

        # Extract previous and new ratings
        fact_map = {f.get("field_name"): f.get("value_json") for f in facts}
        prev_rating = event.get("previous_rating") or (fact_map.get("previous_rating") or "").strip('"')
        new_rating = event.get("new_rating") or (fact_map.get("new_rating") or "").strip('"')

        notch_change = calculate_rating_notch_change(prev_rating, new_rating)
        # Require positive rating notch change (>= 1.0 notch)
        if notch_change is None or notch_change < 1.0:
            return None

        # Conviction scales with notch improvement (e.g. 2 notches = 0.8, 1 notch = 0.6)
        conviction = min(1.0, 0.5 + (notch_change * 0.15))

        return StrategySignal(
            strategy_id=self.strategy_id,
            symbol=event["symbol"],
            side="BUY",
            conviction_score=conviction,
            holding_sessions=20,
            stop_loss_pct=6.0,
            target_pct=15.0,
            rationale=f"Credit rating upgrade of {notch_change:.1f} notches ({prev_rating} -> {new_rating})",
        )
