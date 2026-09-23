from __future__ import annotations

from qual_event_engine.domain.models import Assessment
from qual_event_engine.strategies.calendar import CalendarStrategy
from qual_event_engine.strategies.credit_upgrade import CreditUpgradeStrategy
from qual_event_engine.strategies.governance import GovernanceStrategy
from qual_event_engine.strategies.order_win import OrderWinStrategy
from qual_event_engine.strategies.registry import get_all_strategies
from qual_event_engine.strategies.tender import TenderStrategy
from qual_event_engine.strategies.usfda import USFDAStrategy


def _assessment(rec: str = "BUY_CANDIDATE") -> Assessment:
    return Assessment(
        recommendation=rec,  # type: ignore[arg-type]
        rationale="Test rationale",
        invalidating_fact="None",
        confidence="HIGH",
        model_id="test",
        prompt_version="v1",
    )


def test_strategy_registry() -> None:
    strats = get_all_strategies()
    assert set(strats.keys()) == {"CR-01", "TN-01", "OR-01", "FD-01", "GV-01", "CL-01"}


def test_cr01_credit_upgrade() -> None:
    strat = CreditUpgradeStrategy()
    event = {
        "event_type": "CREDIT_UPGRADE",
        "firmness_level": 5,
        "symbol": "APEX",
        "previous_rating": "A",
        "new_rating": "AA",
    }
    sig = strat.evaluate(event, [], _assessment())
    assert sig is not None
    assert sig.strategy_id == "CR-01"
    assert sig.side == "BUY"
    assert sig.conviction_score > 0.5


def test_tn01_tender() -> None:
    strat = TenderStrategy()
    event = {
        "event_type": "EXECUTED_CONTRACT",
        "firmness_level": 5,
        "symbol": "INFRA",
        "materiality_ratio": 0.20,
    }
    sig = strat.evaluate(event, [], _assessment())
    assert sig is not None
    assert sig.strategy_id == "TN-01"
    assert sig.side == "BUY"


def test_or01_order_win() -> None:
    strat = OrderWinStrategy()
    event = {
        "event_type": "ORDER_WIN",
        "firmness_level": 4,
        "symbol": "TECHCO",
        "event_value_inr": 200_000_000,
        "ttm_revenue_inr": 800_000_000,  # 25% materiality
    }
    sig = strat.evaluate(event, [], _assessment())
    assert sig is not None
    assert sig.strategy_id == "OR-01"
    assert sig.side == "BUY"


def test_fd01_usfda() -> None:
    strat = USFDAStrategy()
    event = {
        "event_type": "USFDA_FINAL_CLASSIFICATION",
        "firmness_level": 5,
        "symbol": "PHARMA",
        "headline": "USFDA issues EIR with NAI status for Facility 1",
    }
    sig = strat.evaluate(event, [], _assessment())
    assert sig is not None
    assert sig.strategy_id == "FD-01"
    assert sig.side == "BUY"


def test_gv01_governance_overlay() -> None:
    strat = GovernanceStrategy()
    event = {
        "event_type": "NEGATIVE_GOVERNANCE",
        "firmness_level": 5,
        "symbol": "BADCO",
        "headline": "Statutory auditor resigns citing governance concerns",
    }
    sig = strat.evaluate(event, [], _assessment("BLOCK"))
    assert sig is not None
    assert sig.strategy_id == "GV-01"
    assert sig.side == "SELL"  # Immediate liquidation / exit
    assert sig.holding_sessions == 0


def test_cl01_calendar() -> None:
    strat = CalendarStrategy()
    event = {
        "event_type": "CALENDAR_EVENT",
        "firmness_level": 4,
        "symbol": "EARLYCO",
        "headline": "Board meeting rescheduled earlier to announce financial results",
    }
    sig = strat.evaluate(event, [], _assessment())
    assert sig is not None
    assert sig.strategy_id == "CL-01"
    assert sig.side == "BUY"
