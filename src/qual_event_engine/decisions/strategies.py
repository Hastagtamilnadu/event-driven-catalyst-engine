from __future__ import annotations

from dataclasses import dataclass

from qual_event_engine.strategies.registry import STRATEGY_REGISTRY


@dataclass(frozen=True, slots=True)
class StrategyEligibility:
    strategy_id: str
    eligible: bool
    reasons: list[str]


class StrategySelector:
    """Selects and validates trading strategies for a given canonical event."""

    @classmethod
    def find_eligible_strategies(
        cls,
        event_type: str,
        firmness_level: int,
        materiality_ratio: float | None = None,
    ) -> list[str]:
        eligible = []
        for strat_id, strat_cls in STRATEGY_REGISTRY.items():
            # Check event type support
            supported_types = getattr(strat_cls, "SUPPORTED_EVENT_TYPES", [])
            min_firmness = getattr(strat_cls, "MIN_FIRMNESS", 1)
            min_materiality = getattr(strat_cls, "MIN_MATERIALITY", 0.0)

            if event_type in supported_types and firmness_level >= min_firmness and (materiality_ratio is None or materiality_ratio >= min_materiality):
                eligible.append(strat_id)
        return eligible
