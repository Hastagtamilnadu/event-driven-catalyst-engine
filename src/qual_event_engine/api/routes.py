from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from qual_event_engine.api.dependencies import get_db_connection
from qual_event_engine.config import load_risk_config, load_strategy_book
from qual_event_engine.operations.health import health_snapshot
from qual_event_engine.research.reports import (
    lead_time_report,
    reconciliation_report,
    strategy_performance_report,
)
from qual_event_engine.runtime import project_root

router = APIRouter()


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    decision: str
    rationale: str = Field(min_length=3, max_length=5000)


@router.get("/health")
def get_health(conn: sqlite3.Connection = Depends(get_db_connection)) -> dict[str, object]:
    return health_snapshot(conn)


@router.get("/sources/health")
def get_sources_health(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT source_id, status, records_observed, message, checked_at_utc
           FROM source_health ORDER BY checked_at_utc DESC"""
    ).fetchall()
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


@router.get("/reports/lead-time")
def get_lead_time_report(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    return lead_time_report(conn)


@router.get("/reports/strategy-performance")
def get_strategy_performance(conn: sqlite3.Connection = Depends(get_db_connection)) -> list[dict[str, object]]:
    return strategy_performance_report(conn)


@router.get("/reports/reconciliation")
def get_reconciliation(
    date: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db_connection),
) -> dict[str, object]:
    return reconciliation_report(conn, as_of_date=date)
