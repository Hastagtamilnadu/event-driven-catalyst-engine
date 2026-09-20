from __future__ import annotations

import os
import sqlite3
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from qual_event_engine.config import load_risk_config, load_strategy_book
from qual_event_engine.decisions.risk import entry_gate
from qual_event_engine.decisions.service import record_review
from qual_event_engine.operations.health import health_snapshot
from qual_event_engine.persistence.database import connect, initialise, transaction
from qual_event_engine.research.reports import (
    lead_time_report,
    reconciliation_report,
    strategy_performance_report,
)
from qual_event_engine.runtime import project_root
from qual_event_engine.settings import Settings

app = FastAPI(title="Qualitative Event Engine", version="0.1.0")


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    decision: str
    rationale: str = Field(min_length=3, max_length=5000)


class CloseIncidentRequest(BaseModel):
    resolution: str = Field(min_length=3, max_length=1000)


def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_directories()
    initialise(settings.db_path)
    return settings


def require_write_token(
    x_qual_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("QUAL_ENGINE_LOCAL_API_TOKEN")
    if expected and x_qual_token != expected:
        raise HTTPException(status_code=401, detail="Invalid local API token")


def _event_or_404(connection: sqlite3.Connection, event_id: str) -> dict[str, object]:
    event = connection.execute(
        "SELECT * FROM canonical_event WHERE event_id=?", (event_id,)
    ).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return dict(event)


@app.get("/health")
def get_health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    with connect(settings.db_path) as connection:
        return health_snapshot(connection)


@app.get("/sources/health")
def get_sources_health(settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    with connect(settings.db_path) as connection:
        rows = connection.execute(
            """SELECT source_id, status, records_observed, message, checked_at_utc
               FROM source_health ORDER BY checked_at_utc DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/strategies")
def get_strategies() -> dict[str, object]:
    root = project_root()
    book, strat_hash = load_strategy_book(root)
    risk, risk_hash = load_risk_config(root)
    return {
        "strategy_config_hash": strat_hash,
        "risk_config_hash": risk_hash,
        "strategies": {k: v.model_dump() for k, v in book.strategies.items()},
        "risk": risk.model_dump(),
    }


@app.get("/events")
def list_events(
    state: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    settings: Settings = Depends(get_settings),
) -> list[dict[str, object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if state:
        clauses.append("e.event_state=?")
        parameters.append(state)
    if source:
        clauses.append("o.source_id=?")
        parameters.append(source)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""SELECT e.*,o.source_id,o.source_url,o.source_published_at_utc,
                       o.exchange_first_seen_at_utc,o.system_first_seen_at_utc,
                       a.recommendation,a.rationale,a.confidence
                FROM canonical_event e
                JOIN source_observation o ON o.observation_id=e.observation_id
                LEFT JOIN analyst_assessment a ON a.event_id=e.event_id
                {where} ORDER BY e.created_at_utc DESC LIMIT ?"""
    parameters.append(limit)
    with connect(settings.db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


@app.get("/events/{event_id}")
def get_event(event_id: str, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    with connect(settings.db_path) as connection:
        event = _event_or_404(connection, event_id)
        event["facts"] = [
            dict(row)
            for row in connection.execute(
                "SELECT field_name,value_json,evidence_text,page_number,validation_status FROM extracted_fact WHERE event_id=?",
                (event_id,),
            ).fetchall()
        ]
        assessment = connection.execute(
            "SELECT * FROM analyst_assessment WHERE event_id=?", (event_id,)
        ).fetchone()
        event["assessment"] = dict(assessment) if assessment else None
        event["reviews"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM review_decision WHERE event_id=? ORDER BY reviewed_at_utc",
                (event_id,),
            ).fetchall()
        ]
        event["orders"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM paper_order WHERE event_id=? ORDER BY created_at_utc", (event_id,)
            ).fetchall()
        ]
        return event


@app.get("/events/{event_id}/evidence")
def get_event_evidence(event_id: str, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Section 33.2 Review screen requirements evidence bundle."""
    with connect(settings.db_path) as connection:
        event = _event_or_404(connection, event_id)

        # 1. Raw source document and observation
        obs = connection.execute(
            """SELECT o.*, r.local_path, r.mime_type, r.bytes, r.page_count,
                      r.extracted_characters, r.extraction_quality, r.parser_status
               FROM source_observation o
               LEFT JOIN raw_document r ON r.raw_sha256 = o.raw_sha256
               WHERE o.observation_id = ?""",
            (event["observation_id"],),
        ).fetchone()
        doc_info = dict(obs) if obs else {}

        # 2. Legal entity match and evidence
        entity = connection.execute(
            "SELECT * FROM entity WHERE entity_id = ? OR primary_isin = ? OR primary_symbol = ?",
            (event["isin"], event["isin"], event["symbol"]),
        ).fetchone()
        entity_info = dict(entity) if entity else {}

        aliases = [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM entity_alias WHERE entity_id = ?",
                (entity_info.get("entity_id", event["isin"]),),
            ).fetchall()
        ]

        relationships = [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM entity_relationship WHERE parent_entity_id = ? OR child_entity_id = ?",
                (entity_info.get("entity_id", event["isin"]), entity_info.get("entity_id", event["isin"])),
            ).fetchall()
        ]

        # 3. Deterministic facts and cited excerpts
        facts = [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM extracted_fact WHERE event_id = ?", (event_id,)
            ).fetchall()
        ]

        # 4. As-of company dossier with missing-data warnings
        membership = connection.execute(
            "SELECT * FROM security_membership WHERE isin = ? OR symbol = ?",
            (event["isin"], event["symbol"]),
        ).fetchone()
        membership_info = dict(membership) if membership else {}

        missing_data_warnings = []
        if not membership_info:
            missing_data_warnings.append("Security is missing from security_membership master.")
        elif not membership_info.get("eligible"):
            missing_data_warnings.append(f"Security marked ineligible: {membership_info.get('eligibility_reasons')}")

        fundamentals = connection.execute(
            "SELECT * FROM point_in_time_fundamental WHERE isin = ? ORDER BY period_end_date DESC LIMIT 1",
            (event["isin"],),
        ).fetchone()
        fund_info = dict(fundamentals) if fundamentals else {}
        if not fund_info:
            missing_data_warnings.append("Point-in-time fundamentals missing for this security.")

        # 5. AI note, model/prompt version, invalidating fact
        assessment = connection.execute(
            "SELECT * FROM analyst_assessment WHERE event_id = ? ORDER BY created_at_utc DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        assessment_info = dict(assessment) if assessment else {}

        # 6. Risk-gate result and reason
        # Pass a sqlite3.Row object to entry_gate
        canonical_row = connection.execute(
            "SELECT * FROM canonical_event WHERE event_id = ?", (event_id,)
        ).fetchone()
        gate_passed, gate_reason = entry_gate(connection, canonical_row) if canonical_row else (False, "Event not found")

        # 7. Strategy configuration version
        root = project_root()
        _strategies, strat_hash = load_strategy_book(root)
        _risk, risk_hash = load_risk_config(root)

        # 8. Immutable previous decisions
        reviews = [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM review_decision WHERE event_id = ? ORDER BY reviewed_at_utc DESC",
                (event_id,),
            ).fetchall()
        ]

        # Check hard locks: blocked entity, incident freeze, stale data
        is_blocked = (
            event["event_state"] == "BLOCKED"
            or not gate_passed
            or (entity_info.get("status") in ("SUSPENDED", "DELISTED"))
        )
        open_incidents = connection.execute(
            "SELECT count(*) FROM incident WHERE status='OPEN'"
        ).fetchone()[0]
        has_freeze = open_incidents > 0 or is_blocked

        return {
            "event": event,
            "document": doc_info,
            "entity": entity_info,
            "aliases": aliases,
            "relationships": relationships,
            "facts": facts,
            "dossier": {
                "membership": membership_info,
                "fundamentals": fund_info,
                "missing_data_warnings": missing_data_warnings,
            },
            "assessment": assessment_info,
            "risk_gate": {
                "passed": gate_passed,
                "reason": gate_reason,
            },
            "configuration": {
                "strategy_book_hash": strat_hash,
                "risk_config_hash": risk_hash,
            },
            "reviews": reviews,
            "hard_gate_lock": {
                "is_locked": has_freeze,
                "reason": "Hard risk gate lock active: review decision cannot bypass blocked entity or open incident"
                if has_freeze
                else None,
            },
        }


@app.post("/events/{event_id}/review", dependencies=[Depends(require_write_token)])
def post_review(
    event_id: str, payload: ReviewRequest, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    with transaction(settings.db_path) as connection:
        _event_or_404(connection, event_id)
        try:
            review_id = record_review(
                connection, event_id, payload.reviewer, payload.decision, payload.rationale
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"review_id": review_id, "status": "recorded"}


@app.post("/incidents/{incident_id}/close", dependencies=[Depends(require_write_token)])
def close_incident(
    incident_id: str, payload: CloseIncidentRequest, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    with transaction(settings.db_path) as connection:
        inc = connection.execute(
            "SELECT * FROM incident WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if not inc:
            raise HTTPException(status_code=404, detail="Incident not found")
        connection.execute(
            """UPDATE incident SET status = 'CLOSED', resolution = ?, closed_at_utc = datetime('now')
               WHERE incident_id = ?""",
            (payload.resolution, incident_id),
        )
    return {"incident_id": incident_id, "status": "CLOSED"}


@app.get("/positions")
def get_positions(settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    with connect(settings.db_path) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM position_lot WHERE status='OPEN' ORDER BY opened_at_utc DESC"
            ).fetchall()
        ]


@app.get("/orders")
def get_orders(settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    with connect(settings.db_path) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM paper_order ORDER BY created_at_utc DESC LIMIT 500"
            ).fetchall()
        ]


@app.get("/reports/performance")
def get_performance(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    with connect(settings.db_path) as connection:
        return {
            "strategy_performance": strategy_performance_report(connection),
            "reconciliation": reconciliation_report(connection),
        }


@app.get("/reports/lead-time")
def get_lead_time(settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    with connect(settings.db_path) as connection:
        return lead_time_report(connection)


@app.get("/reports/{report_id}")
def get_report(report_id: str, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    with connect(settings.db_path) as connection:
        if report_id == "performance":
            return {
                "strategy_performance": strategy_performance_report(connection),
                "reconciliation": reconciliation_report(connection),
            }
        elif report_id == "lead-time":
            return {"lead_time": lead_time_report(connection)}
        elif report_id == "reconciliation":
            return {"reconciliation": reconciliation_report(connection)}
        else:
            raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
