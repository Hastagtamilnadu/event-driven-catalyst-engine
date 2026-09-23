from __future__ import annotations

from datetime import time

from qual_event_engine.operations.scheduler import SCHEDULE_PHASES, DailyScheduler


def test_scheduler_phases() -> None:
    scheduler = DailyScheduler()
    assert len(SCHEDULE_PHASES) == 6

    # Test phase determination across the day
    p1 = scheduler.determine_current_phase(time(6, 30))
    assert p1.name == "OVERNIGHT_INGESTION"

    p2 = scheduler.determine_current_phase(time(8, 45))
    assert p2.name == "PRE_MARKET_ALIGNMENT"

    p3 = scheduler.determine_current_phase(time(11, 0))
    assert p3.name == "INTRADAY_EXECUTION"

    p4 = scheduler.determine_current_phase(time(16, 15))
    assert p4.name == "POST_MARKET_RECONCILIATION"

    p5 = scheduler.determine_current_phase(time(18, 30))
    assert p5.name == "PIT_DATA_INGESTION"

    p6 = scheduler.determine_current_phase(time(21, 30))
    assert p6.name == "NIGHTLY_INTEGRITY"


def test_scheduler_execution() -> None:
    scheduler = DailyScheduler()
    scheduler.register_handler("OVERNIGHT_INGESTION", lambda: {"events_ingested": 10})
    result = scheduler.execute_phase("OVERNIGHT_INGESTION")
    assert result.status == "SUCCEEDED"
    assert result.details["events_ingested"] == 10

    unregistered = scheduler.execute_phase("NON_EXISTENT")
    assert unregistered.status == "SKIPPED"
