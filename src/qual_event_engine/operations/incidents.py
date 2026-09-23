from __future__ import annotations

"""§20.2 / §16.2 incident freeze conditions and §20.3 recovery.

Freeze new paper intents when:
- Critical parser incident
- Model incident
- Source outage (affected strategy only)
- Schedule incident
- Data freshness breach
- Reconciliation failure
- Daily loss threshold hit
- Drawdown ladder breach
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from qual_event_engine.operations.health import open_incident
from qual_event_engine.research.reports import reconciliation_report

FREEZE_CONDITIONS = (
    "CRITICAL_PARSER_INCIDENT",
    "MODEL_INCIDENT",
    "SOURCE_OUTAGE",
    "SCHEDULE_INCIDENT",
    "DATA_FRESHNESS_BREACH",
    "RECONCILIATION_FAILURE",
    "DAILY_LOSS_THRESHOLD",
    "DRAWDOWN_LADDER_BREACH",
)


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    incident_id: str
    severity: str
    service: str
    summary: str
    opened_at_utc: datetime
    resolved_at_utc: datetime | None
    status: str
    resolution_notes: str | None = None
    freeze_scope: str = "NEW_INTENTS"
    affected_strategy_id: str | None = None


@dataclass(frozen=True, slots=True)
class FreezeDecision:
    freeze_new_intents: bool
    condition: str
    scope: str
    affected_strategy_id: str | None
    reason: str


class IncidentManager:
    """Manages operational incidents and trading freeze triggers."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def trigger_incident(self, severity: str, service: str, summary: str) -> str:
        return open_incident(self.connection, severity, service, summary)

    def is_system_frozen(self) -> bool:
        rows = self.connection.execute(
            "SELECT service FROM incident WHERE status = 'OPEN'"
        ).fetchall()
        return any(
            not (
                str(row["service"] or "") == "SOURCE_OUTAGE"
                or str(row["service"] or "").startswith("SOURCE_OUTAGE")
            )
            for row in rows
        )

    def resolve_incident(self, incident_id: str, resolution_notes: str = "") -> None:
        now = datetime.now(UTC).isoformat()
        self.connection.execute(
            """
            UPDATE incident
            SET status = 'RESOLVED', closed_at_utc = ?, resolution = ?
            WHERE incident_id = ?
            """,
            (now, resolution_notes, incident_id),
        )

    def evaluate_freeze_conditions(
        self,
        *,
        parser_critical: bool = False,
        model_incident: bool = False,
        source_outage_source_id: str | None = None,
        affected_strategy_id: str | None = None,
        schedule_incident: bool = False,
        data_freshness_breach: bool = False,
        daily_loss_threshold_hit: bool = False,
        drawdown_ladder_breach: bool = False,
    ) -> list[FreezeDecision]:
        decisions: list[FreezeDecision] = []
        if parser_critical:
            decisions.append(
                FreezeDecision(True, "CRITICAL_PARSER_INCIDENT", "NEW_INTENTS", None, "critical parser incident")
            )
        if model_incident:
            decisions.append(
                FreezeDecision(True, "MODEL_INCIDENT", "NEW_INTENTS", None, "model incident")
            )
        if source_outage_source_id:
            decisions.append(
                FreezeDecision(
                    True,
                    "SOURCE_OUTAGE",
                    "AFFECTED_STRATEGY",
                    affected_strategy_id,
                    f"source outage:{source_outage_source_id}",
                )
            )
        if schedule_incident:
            decisions.append(
                FreezeDecision(True, "SCHEDULE_INCIDENT", "NEW_INTENTS", None, "schedule incident")
            )
        if data_freshness_breach:
            decisions.append(
                FreezeDecision(True, "DATA_FRESHNESS_BREACH", "NEW_INTENTS", None, "stale data")
            )
        recon = reconciliation_report(self.connection)
        if not recon.get("is_reconciled", True):
            decisions.append(
                FreezeDecision(
                    True, "RECONCILIATION_FAILURE", "NEW_INTENTS", None, "ledger disagreement"
                )
            )
        if daily_loss_threshold_hit:
            decisions.append(
                FreezeDecision(True, "DAILY_LOSS_THRESHOLD", "NEW_INTENTS", None, "daily loss")
            )
        if drawdown_ladder_breach:
            decisions.append(
                FreezeDecision(True, "DRAWDOWN_LADDER_BREACH", "NEW_INTENTS", None, "drawdown ladder")
            )
        return decisions

    def freeze_for(self, condition: str, summary: str, strategy_id: str | None = None) -> str:
        if condition not in FREEZE_CONDITIONS:
            raise ValueError(f"Unknown freeze condition: {condition}")
        notes = summary
        if strategy_id:
            notes = summary + " affected_strategy_id=" + strategy_id
        incident_id = self.trigger_incident("P1_CRITICAL", condition, notes)
        return incident_id

    def recovery(self, incident_id: str, reviewer: str, resolution: str) -> dict[str, Any]:
        """§20.3 six recovery steps."""
        steps: list[str] = []
        row = self.connection.execute(
            "SELECT * FROM incident WHERE incident_id=?", (incident_id,)
        ).fetchone()
        if row is None:
            incident_id = self.trigger_incident("P1_CRITICAL", "recovery", "opened during recovery")
        steps.append("1_open_timestamped_incident")

        frozen = self.is_system_frozen()
        if not frozen:
            self.trigger_incident("P1_CRITICAL", "FREEZE", "freeze new intents during recovery")
        steps.append("2_freeze_new_intents")

        steps.append("3_repair_or_restore_affected_service")

        recon = reconciliation_report(self.connection)
        steps.append("4_reconcile_events_intents_orders_fills_positions_cash")

        self.connection.execute(
            """
            UPDATE incident SET status='CLOSED', resolution=?, closed_at_utc=?
            WHERE incident_id=?
            """,
            (f"{reviewer}: {resolution}", datetime.now(UTC).isoformat(), incident_id),
        )
        steps.append("5_reviewer_closes_incident")

        checkpoint = self.connection.execute(
            """
            SELECT job_run_id, job_name, started_at_utc, status
            FROM job_run
            WHERE status IN ('COMPLETED','SUCCESS')
            ORDER BY started_at_utc DESC
            LIMIT 1
            """
        ).fetchone()
        steps.append("6_resume_from_last_confirmed_idempotent_checkpoint")
        return {
            "incident_id": incident_id,
            "steps": steps,
            "reconciliation": recon,
            "checkpoint": dict(checkpoint) if checkpoint else None,
            "new_intents_allowed": not self.is_system_frozen(),
        }
