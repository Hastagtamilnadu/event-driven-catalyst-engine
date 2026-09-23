from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any


@dataclass(frozen=True, slots=True)
class SchedulePhaseDefinition:
    phase: int
    name: str
    time_ist: time
    description: str


# Operating Schedule Phase Definitions (§4)
SCHEDULE_PHASES: list[SchedulePhaseDefinition] = [
    SchedulePhaseDefinition(
        phase=1,
        name="OVERNIGHT_INGESTION",
        time_ist=time(6, 0),
        description="Overnight exchange disclosures and filings ingestion, entity resolution",
    ),
    SchedulePhaseDefinition(
        phase=2,
        name="PRE_MARKET_ALIGNMENT",
        time_ist=time(8, 30),
        description="Pre-market risk assessment, universe membership check, order intent generation",
    ),
    SchedulePhaseDefinition(
        phase=3,
        name="INTRADAY_EXECUTION",
        time_ist=time(9, 15),
        description="Intraday event processing, price bar monitoring, order fill execution",
    ),
    SchedulePhaseDefinition(
        phase=4,
        name="POST_MARKET_RECONCILIATION",
        time_ist=time(16, 0),
        description="Post-market trade reconciliation, position accounting, cash ledger verification",
    ),
    SchedulePhaseDefinition(
        phase=5,
        name="PIT_DATA_INGESTION",
        time_ist=time(18, 0),
        description="Corporate action ingestion, point-in-time fundamentals update, split adjustments",
    ),
    SchedulePhaseDefinition(
        phase=6,
        name="NIGHTLY_INTEGRITY",
        time_ist=time(21, 0),
        description="Nightly ledger backup, integrity verification, source health snapshot",
    ),
]


@dataclass(frozen=True, slots=True)
class PhaseExecutionResult:
    phase_number: int
    phase_name: str
    executed_at_utc: str
    status: str  # "SUCCEEDED", "FAILED", "SKIPPED"
    details: dict[str, Any]


class DailyScheduler:
    """Orchestrator for the 6-phase daily operating schedule (§4)."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[], dict[str, Any]]] = {}

    def register_handler(self, phase_name: str, handler: Callable[[], dict[str, Any]]) -> None:
        self._handlers[phase_name] = handler

    def determine_current_phase(self, current_ist_time: time) -> SchedulePhaseDefinition:
        """Returns the appropriate active or upcoming operating phase."""
        for phase in reversed(SCHEDULE_PHASES):
            if current_ist_time >= phase.time_ist:
                return phase
        return SCHEDULE_PHASES[0]

    def execute_phase(self, phase_name: str) -> PhaseExecutionResult:
        handler = self._handlers.get(phase_name)
        now_utc = datetime.now(UTC).isoformat()
        if not handler:
            return PhaseExecutionResult(
                phase_number=0,
                phase_name=phase_name,
                executed_at_utc=now_utc,
                status="SKIPPED",
                details={"reason": "No handler registered"},
            )

        try:
            details = dict(handler())
            details.setdefault("idempotent_checkpoint", phase_name)
            return PhaseExecutionResult(
                phase_number=0,
                phase_name=phase_name,
                executed_at_utc=now_utc,
                status="SUCCEEDED",
                details=details,
            )
        except Exception as exc:  # noqa: BLE001
            return PhaseExecutionResult(
                phase_number=0,
                phase_name=phase_name,
                executed_at_utc=now_utc,
                status="FAILED",
                details={"error": str(exc)},
            )
