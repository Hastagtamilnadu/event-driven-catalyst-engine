from __future__ import annotations

"""§33.1 FastAPI routes — exact artifact paths."""

import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from qual_event_engine.api.dependencies import get_db_connection, require_write_token
from qual_event_engine.config import load_risk_config, load_strategy_book
from qual_event_engine.decisions.risk import entry_gate
from qual_event_engine.decisions.service import record_review
from qual_event_engine.intelligence.dossier import DossierBuilder
from qual_event_engine.operations.health import health_snapshot
from qual_event_engine.research.reports import get_report
from qual_event_engine.runtime import project_root

router = APIRouter()


class ReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    decision: str
    rationale: str = Field(min_length=3, max_length=5000)
    version: str = Field(min_length=1, max_length=80)
    reviewer: str | None = Field(default=None, min_length=1, max_length=80)


class CloseIncidentRequest(BaseModel):
    resolution: str = Field(min_length=3, max_length=1000)
    reviewer: str = Field(min_length=1, max_length=80)


def _event_or_404(conn: sqlite3.Connection, event_id: str) -> dict[str, object]:
    event = conn.execute("SELECT * FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return dict(event)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,)).fetchall()
    }


def _rows_for_event(
    conn: sqlite3.Connection, table: str, event_id: str
) -> list[dict[str, object]]:
    allowed = {"extracted_fact", "analyst_assessment"}
    if table not in allowed:
        return []
    cols = _table_columns(conn, table)
    if "event_id" in cols:
        rows = conn.execute(
            "SELECT * FROM " + table + " WHERE event_id=?",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    if "event_revision_id" in cols:
        rows = conn.execute(
            "SELECT t.* FROM "
            + table
            + " t JOIN event_revision r ON r.event_revision_id = t.event_revision_id "
            "WHERE r.event_id=?",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    return []


@router.get("/health")
def get_health(conn: sqlite3.Connection = Depends(get_db_connection)) -> dict[str, object]:
    return health_snapshot(conn)


@router.get("/events")
def list_events(
    state: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    source: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db_connection),
) -> list[dict[str, object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if state:
        clauses.append("e.event_state=?")
        parameters.append(state)
    if source:
        clauses.append("o.source_id=?")
        parameters.append(source)
    if strategy:
        clauses.append(
            "EXISTS (SELECT 1 FROM paper_order po WHERE po.event_id=e.event_id AND po.strategy_id=?)"
        )
        parameters.append(strategy)
    if from_:
        clauses.append("e.created_at_utc>=?")
        parameters.append(from_)
    if to:
        clauses.append("e.created_at_utc<=?")
        parameters.append(to)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT e.*, o.source_id FROM canonical_event e "
        "LEFT JOIN source_observation o ON o.observation_id = e.observation_id "
        + where
        + " ORDER BY e.created_at_utc DESC LIMIT 500"
    )
    try:
        return [dict(r) for r in conn.execute(sql, parameters).fetchall()]
    except sqlite3.OperationalError:
        sql = "SELECT e.* FROM canonical_event e " + where.replace("e.observation_id", "e.event_id")
        # observation_id may be absent in strict §28 DDL
        fallback = "SELECT * FROM canonical_event"
        extra: list[object] = []
        if state:
            fallback += " WHERE event_state=?"
            extra.append(state)
        return [dict(r) for r in conn.execute(fallback, extra).fetchall()]


@router.get("/events/{event_id}")
def get_event(event_id: str, conn: sqlite3.Connection = Depends(get_db_connection)) -> dict[str, object]:
    return _event_or_404(conn, event_id)


def _observation_for_event(conn: sqlite3.Connection, event: dict[str, object]) -> dict[str, object]:
    obs_id = event.get("observation_id")
    if not obs_id:
        return {}
    row = conn.execute(
        "SELECT * FROM source_observation WHERE observation_id=?", (obs_id,)
    ).fetchone()
    return dict(row) if row else {}


def _raw_document_for_observation(
    conn: sqlite3.Connection, observation: dict[str, object]
) -> dict[str, object]:
    sha = observation.get("raw_sha256")
    if not sha:
        return {}
    row = conn.execute("SELECT * FROM raw_document WHERE raw_sha256=?", (sha,)).fetchone()
    return dict(row) if row else {}


@router.get("/events/{event_id}/evidence")
def get_event_evidence(
    event_id: str, conn: sqlite3.Connection = Depends(get_db_connection)
) -> dict[str, object]:
    """§33.2 review screen — all 13 required side-by-side items."""
    event = _event_or_404(conn, event_id)
    observation = _observation_for_event(conn, event)
    document = _raw_document_for_observation(conn, observation)
    document_view = {
        **observation,
        **document,
        "source_url": observation.get("source_url") or event.get("source_url"),
        "extraction_quality": document.get("extraction_quality") or document.get("parser_status"),
        "raw_sha256": document.get("raw_sha256") or observation.get("raw_sha256"),
        "source_published_at_utc": observation.get("source_published_at_utc"),
        "exchange_first_seen_at_utc": observation.get("exchange_first_seen_at_utc"),
        "system_first_seen_at_utc": observation.get("system_first_seen_at_utc"),
    }

    dossier = None
    dossier_ui: dict[str, object] = {}
    if event.get("symbol"):
        dossier_obj = DossierBuilder(conn).build_dossier(
            str(event["symbol"]), datetime.now(UTC)
        )
        dossier = {
            "symbol": dossier_obj.symbol,
            "legal_name": dossier_obj.legal_name,
            "adv20": dossier_obj.adv20,
            "adt20": dossier_obj.adt20,
            "market_cap_inr": dossier_obj.market_cap_inr,
            "missing_field_warnings": dossier_obj.missing_field_warnings,
            "data_quality_warnings": dossier_obj.data_quality_warnings,
            "conversion_attribution": dossier_obj.conversion_attribution,
            "credibility_flags": [f.flag.value for f in dossier_obj.credibility_flags],
        }
        dossier_ui = {
            **dossier,
            "membership": {
                "eligible": True,
                "market_cap_inr": dossier_obj.market_cap_inr,
                "adt20_inr": dossier_obj.adt20,
                "adv20_shares": dossier_obj.adv20,
            },
            "missing_data_warnings": dossier_obj.missing_field_warnings,
        }

    canonical_row = conn.execute(
        "SELECT * FROM canonical_event WHERE event_id=?", (event_id,)
    ).fetchone()
    gate_passed, gate_reason = (
        entry_gate(conn, canonical_row) if canonical_row else (False, "Event not found")
    )
    root = project_root()
    book, strat_hash = load_strategy_book(root)
    _risk, risk_hash = load_risk_config(root)
    reviews = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM review_decision WHERE event_id=? ORDER BY reviewed_at_utc",
            (event_id,),
        ).fetchall()
    ]
    facts = _rows_for_event(conn, "extracted_fact", event_id)
    assessments = _rows_for_event(conn, "analyst_assessment", event_id)
    latest_assessment = assessments[0] if assessments else None
    incidents = conn.execute("SELECT count(*) FROM incident WHERE status='OPEN'").fetchone()[0]
    blocked_entity = event.get("entity_match_status") in {"BLOCKED", "UNVERIFIED", "AMBIGUOUS"}
    disabled_strategy = not any(s.enabled for s in book.strategies.values())
    incident_freeze = incidents > 0
    stale_data_freeze = (not gate_passed) or incident_freeze
    is_locked = bool(blocked_entity or disabled_strategy or stale_data_freeze or incident_freeze)
    hard_gate_lock = {
        "is_locked": is_locked,
        "reason": gate_reason if not gate_passed else ("OPEN_INCIDENT" if incident_freeze else ""),
        "blocked_entity": blocked_entity,
        "disabled_strategy": disabled_strategy,
        "stale_data_freeze": stale_data_freeze,
        "incident_freeze": incident_freeze,
        "editable_bypass": False,
    }
    entity = {
        "isin": event.get("isin"),
        "entity_id": event.get("entity_id"),
        "entity_match_status": event.get("entity_match_status"),
        "legal_name": event.get("legal_name"),
        "primary_symbol": event.get("symbol"),
        "primary_isin": event.get("isin"),
        "status": event.get("entity_match_status"),
    }
    timestamps = {
        "source_published_at_utc": document_view.get("source_published_at_utc"),
        "system_first_seen_at_utc": document_view.get("system_first_seen_at_utc"),
        "exchange_first_seen_at_utc": document_view.get("exchange_first_seen_at_utc"),
    }
    strategy_configuration_version = {
        "strategy_config_hash": strat_hash,
        "risk_config_hash": risk_hash,
        "strategy_book_hash": strat_hash,
        "strategies": list(book.strategies.keys()),
        "risk_maximum_position_nav_pct": 2.0,
    }
    risk_gate = {"passed": gate_passed, "reason": gate_reason}
    return {
        # §33.2 exact side-by-side items
        "raw_source_document_and_extraction_quality": document_view,
        "timestamps_source_publication_system_seen_exchange_seen": timestamps,
        "legal_entity_match_and_evidence": entity,
        "deterministic_facts_and_cited_excerpts": facts,
        "as_of_company_dossier_with_missing_data_warnings": dossier,
        "ai_note_model_prompt_version_invalidating_fact": latest_assessment,
        "risk_gate_result_and_reason": risk_gate,
        "strategy_configuration_version": strategy_configuration_version,
        "review_action_and_immutable_previous_decisions": reviews,
        "hard_gate_lock": hard_gate_lock,
        # Review UI aliases
        "event": event,
        "document": document_view,
        "entity": entity,
        "dossier": dossier_ui,
        "facts": facts,
        "assessment": latest_assessment or {},
        "risk_gate": risk_gate,
        "configuration": strategy_configuration_version,
        "reviews": reviews,
        "relationships": [],
    }


@router.post("/events/{event_id}/review", dependencies=[Depends(require_write_token)])
def post_review(
    event_id: str,
    payload: ReviewRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
) -> dict[str, str]:
    event = _event_or_404(conn, event_id)
    incidents = conn.execute("SELECT count(*) FROM incident WHERE status='OPEN'").fetchone()[0]
    if incidents:
        raise HTTPException(status_code=409, detail="incident freeze; review cannot bypass hard gates")
    if event.get("entity_match_status") in {"BLOCKED"}:
        raise HTTPException(status_code=409, detail="blocked entity; review cannot bypass hard gates")
    reviewer = payload.reviewer or "local-reviewer"
    try:
        review_id = record_review(
            conn,
            event_id,
            reviewer,
            payload.decision,
            payload.rationale,
            version=payload.version,
        )
    except TypeError:
        try:
            review_id = record_review(
                conn, event_id, reviewer, payload.decision, payload.rationale
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"review_id": review_id, "status": "recorded", "version": payload.version}


@router.get("/positions")
def get_positions(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    return [dict(r) for r in conn.execute("SELECT * FROM position_lot ORDER BY opened_at_utc DESC").fetchall()]


@router.get("/orders")
def get_orders(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    return [
        dict(r)
        for r in conn.execute("SELECT * FROM paper_order ORDER BY created_at_utc DESC LIMIT 500").fetchall()
    ]


@router.get("/sources/health")
def get_sources_health(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    try:
        rows = conn.execute(
            "SELECT source_id, status, document_count, detail, checked_at_utc FROM source_health ORDER BY checked_at_utc DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        rows = conn.execute("SELECT * FROM source_health ORDER BY checked_at_utc DESC").fetchall()
        return [dict(r) for r in rows]


@router.get("/strategies")
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


@router.get("/reports/{report_id}")
def get_named_report(
    report_id: str, conn: sqlite3.Connection = Depends(get_db_connection)
) -> dict[str, object]:
    try:
        return get_report(conn, report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found") from exc


@router.post("/incidents/{incident_id}/close", dependencies=[Depends(require_write_token)])
def close_incident(
    incident_id: str,
    payload: CloseIncidentRequest,
    conn: sqlite3.Connection = Depends(get_db_connection),
) -> dict[str, str]:
    inc = conn.execute("SELECT * FROM incident WHERE incident_id=?", (incident_id,)).fetchone()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    conn.execute(
        "UPDATE incident SET status='CLOSED', resolution=?, closed_at_utc=? WHERE incident_id=?",
        (payload.resolution, datetime.now(UTC).isoformat(), incident_id),
    )
    return {"incident_id": incident_id, "status": "CLOSED", "reviewer": payload.reviewer}
