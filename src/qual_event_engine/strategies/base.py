from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from qual_event_engine.domain.models import Assessment


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    conviction_score: float  # 0.0 to 1.0
    holding_sessions: int
    stop_loss_pct: float
    target_pct: float | None
    rationale: str


class BaseStrategy(ABC):
    strategy_id: str
    name: str
    event_types: ClassVar[list[str]]

    @abstractmethod
    def evaluate(
        self,
        event: dict[str, Any],
        facts: list[dict[str, Any]],
        assessment: Assessment,
    ) -> StrategySignal | None:
        """Evaluates event facts and assessment to generate an actionable strategy signal."""
