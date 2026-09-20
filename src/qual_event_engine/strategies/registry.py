from __future__ import annotations

from qual_event_engine.strategies.base import BaseStrategy
from qual_event_engine.strategies.calendar import CalendarStrategy
from qual_event_engine.strategies.credit_upgrade import CreditUpgradeStrategy
from qual_event_engine.strategies.governance import GovernanceStrategy
from qual_event_engine.strategies.order_win import OrderWinStrategy
from qual_event_engine.strategies.tender import TenderStrategy
from qual_event_engine.strategies.usfda import USFDAStrategy

STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "CR-01": CreditUpgradeStrategy,
    "TN-01": TenderStrategy,
    "OR-01": OrderWinStrategy,
    "FD-01": USFDAStrategy,
    "GV-01": GovernanceStrategy,
    "CL-01": CalendarStrategy,
}
STRATEGY_REGISTRY = STRATEGY_CLASSES


def get_all_strategies() -> dict[str, BaseStrategy]:
    return {strat_id: cls() for strat_id, cls in STRATEGY_CLASSES.items()}
