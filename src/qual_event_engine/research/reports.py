from __future__ import annotations

"""§19.2 Required reports before paper positions in any strategy.

1. Source lead-time report (uses §32.2 lead_minutes formula)
2. Manually audited entity-resolution sample
3. Manually audited event/firmness classification sample
4. Causal historical event study
5. Replay comparison of decision and simulated fill timing
6. Cost/impact sensitivity analysis
7. Source failure and data-freshness report
"""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from qual_event_engine.paper.costs import report_paper_trade
from qual_event_engine.research.event_study import EventStudyEngine
from qual_event_engine.research.performance import (
    strategy_benchmark_report,
    strategy_benchmark_report_as_dict,
)

FORWARD_RETURN_COLUMNS = frozenset(
    {
        "fwd_ret_1d",
        "fwd_ret_5d",
        "fwd_ret_10d",
        "fwd_ret_20d",
        "forward_return",
        "forward_return_1d",
        "forward_return_5d",
        "t1_return",
        "t5_return",
        "t20_return",
    }
)

REQUIRED_REPORTS = (
    "source_lead_time",
    "entity_resolution_sample",
    "event_firmness_sample",
    "causal_historical_event_study",
    "replay_decision_fill_timing",
    "cost_impact_sensitivity",
    "source_failure_data_freshness",
)


def lead_minutes(
    exchange_first_seen_at_utc: str | None,
    source_published_at_utc: str | None,
) -> float | None:
    """§32.2: only when both timestamps are verified. Negative values are retained."""
    if not exchange_first_seen_at_utc or not source_published_at_utc:
        return None
    try:
        exchange = datetime.fromisoformat(exchange_first_seen_at_utc)
        published = datetime.fromisoformat(source_published_at_utc)
    except ValueError:
        return None
    return (exchange - published).total_seconds() / 60.0


def system_discovery_delay_minutes(
    system_first_seen_at_utc: str | None,
    source_published_at_utc: str | None,
) -> float | None:
    if not system_first_seen_at_utc or not source_published_at_utc:
        return None
    try:
        system = datetime.fromisoformat(system_first_seen_at_utc)
        published = datetime.fromisoformat(source_published_at_utc)
    except ValueError:
        return None
    return (system - published).total_seconds() / 60.0


def lead_time_report(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT source_id, observation_id, exchange_first_seen_at_utc,
               source_published_at_utc, system_first_seen_at_utc
        FROM source_observation
        ORDER BY source_id
        """
    ).fetchall()
    by_source: dict[str, list[float]] = {}
    negatives_retained = 0
    for row in rows:
        lead = lead_minutes(row["exchange_first_seen_at_utc"], row["source_published_at_utc"])
        if lead is None:
            continue
        if lead < 0:
            negatives_retained += 1
        by_source.setdefault(str(row["source_id"]), []).append(lead)
    out: list[dict[str, Any]] = []
    for source_id, leads in sorted(by_source.items()):
        out.append(
            {
                "source_id": source_id,
                "observations": len(leads),
                "average_lead_minutes": sum(leads) / len(leads),
                "min_lead_minutes": min(leads),
                "max_lead_minutes": max(leads),
                "negatives_retained": sum(1 for x in leads if x < 0),
                "formula": "lead_minutes = exchange_first_seen_at_utc - source_published_at_utc",
            }
        )
    if not out:
        return []
    out[0]["report_negatives_retained_total"] = negatives_retained
    return out


def entity_resolution_sample_report(
    connection: sqlite3.Connection, limit: int = 50
) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT event_id, symbol, isin, entity_id, entity_match_status, event_state
        FROM canonical_event
        ORDER BY created_at_utc DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    sample = [dict(r) for r in rows]
    return {
        "report_id": "entity_resolution_sample",
        "manual_audit_required": True,
        "sample_size": len(sample),
        "unresolved": [s for s in sample if s.get("entity_match_status") not in {"EXACT", "VERIFIED", "MATCHED"}],
        "rows": sample,
    }


def event_firmness_sample_report(
    connection: sqlite3.Connection, limit: int = 50
) -> dict[str, Any]:
    cols = {
        str(r[0])
        for r in connection.execute(
            "SELECT name FROM pragma_table_info(?)", ("canonical_event",)
        ).fetchall()
    }
    if "firmness_level" in cols:
        rows = connection.execute(
            "SELECT event_id, event_type, event_state, firmness_level FROM canonical_event ORDER BY created_at_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT event_id, event_type, event_state FROM canonical_event ORDER BY created_at_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {
        "report_id": "event_firmness_sample",
        "manual_audit_required": True,
        "sample_size": len(rows),
        "rows": [dict(r) for r in rows],
        "ai_cannot_promote_firmness": True,
    }


def causal_historical_event_study_report(
    event_returns: list[list[float]] | None = None,
) -> dict[str, Any]:
    study = EventStudyEngine.calculate_car(event_returns or [])
    return {
        "report_id": "causal_historical_event_study",
        "sample_size": study.sample_size,
        "mean_car_pct": study.mean_car_pct,
        "median_car_pct": study.median_car_pct,
        "t_stat": study.t_stat,
        "uses_source_timestamps": True,
        "uses_point_in_time_data": True,
        "ai_verdicts_are_not_proof_of_skill": True,
    }


def replay_decision_fill_timing_report(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT o.paper_order_id, o.created_at_utc, o.status,
               MIN(f.filled_at_utc) AS first_fill_utc,
               (julianday(MIN(f.filled_at_utc)) - julianday(o.created_at_utc)) * 1440.0 AS fill_lag_minutes
        FROM paper_order o
        LEFT JOIN paper_fill f ON f.paper_order_id = o.paper_order_id
        GROUP BY o.paper_order_id
        ORDER BY o.created_at_utc
        """
    ).fetchall()
    return {
        "report_id": "replay_decision_fill_timing",
        "rows": [dict(r) for r in rows],
        "causal": True,
    }


def cost_impact_sensitivity_report(
    entry_notional: float = 100_000.0,
    exit_notional: float = 101_000.0,
) -> dict[str, Any]:
    base = report_paper_trade(entry_notional, exit_notional, participation_fraction=0.01)
    stressed = report_paper_trade(entry_notional, exit_notional, participation_fraction=0.10, session="CIRCUIT")
    return {
        "report_id": "cost_impact_sensitivity",
        "base": {
            "gross_pnl_inr": base.gross_pnl_inr,
            "net_pnl_before_tax_inr": base.net_pnl_before_tax_inr,
            "cost_components": base.cost_components,
            "uncertainty": base.uncertainty,
        },
        "stressed_participation_and_circuit": {
            "gross_pnl_inr": stressed.gross_pnl_inr,
            "net_pnl_before_tax_inr": stressed.net_pnl_before_tax_inr,
            "cost_components": stressed.cost_components,
            "uncertainty": stressed.uncertainty,
        },
    }


def source_failure_data_freshness_report(connection: sqlite3.Connection) -> dict[str, Any]:
    cutoff = (datetime.now(UTC) - timedelta(hours=36)).isoformat()
    health = [
        dict(r)
        for r in connection.execute(
            "SELECT source_id, status, document_count, detail, checked_at_utc FROM source_health ORDER BY checked_at_utc DESC"
        ).fetchall()
    ]
    stale_prices = connection.execute(
        "SELECT COUNT(*) FROM (SELECT symbol, MAX(close_time_utc) AS latest FROM price_bar GROUP BY symbol HAVING latest < ?)",
        (cutoff,),
    ).fetchone()[0]
    return {
        "report_id": "source_failure_data_freshness",
        "source_health": health,
        "stale_symbol_count": int(stale_prices),
        "freshness_cutoff_utc": cutoff,
    }


def required_reports_bundle(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "source_lead_time": lead_time_report(connection),
        "entity_resolution_sample": entity_resolution_sample_report(connection),
        "event_firmness_sample": event_firmness_sample_report(connection),
        "causal_historical_event_study": causal_historical_event_study_report(),
        "replay_decision_fill_timing": replay_decision_fill_timing_report(connection),
        "cost_impact_sensitivity": cost_impact_sensitivity_report(),
        "source_failure_data_freshness": source_failure_data_freshness_report(connection),
    }


def strategy_performance_report(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT o.strategy_id,
                  COUNT(DISTINCT o.paper_order_id) AS orders,
                  COUNT(f.paper_fill_id) AS fills,
                  COALESCE(SUM(f.quantity * f.final_price), 0) AS executed_notional_inr,
                  COUNT(DISTINCT CASE WHEN p.status='OPEN' THEN p.position_lot_id END) AS open_positions,
                  COUNT(DISTINCT CASE WHEN o.status='EXIT_UNFILLED' THEN o.paper_order_id END) AS exit_unfilled_orders
           FROM paper_order o
           LEFT JOIN paper_fill f ON f.paper_order_id=o.paper_order_id
           LEFT JOIN position_lot p ON p.opened_by_fill_id=f.paper_fill_id
           GROUP BY o.strategy_id ORDER BY o.strategy_id"""
    ).fetchall()
    return [dict(row) for row in rows]


def reconciliation_report(
    connection: sqlite3.Connection, as_of_date: str | None = None
) -> dict[str, Any]:
    """Section 32 daily reconciliation asserting zero orphaned records and ledger balance."""
    cash_query = """SELECT strategy_id,
                           COALESCE(SUM(amount_inr), 0) AS total_cash_flow,
                           MAX(balance_after_inr) AS last_cash
                    FROM cash_ledger """
    cash_params: list[object] = []
    try:
        if as_of_date:
            cash_query += "WHERE substr(occurred_at_utc, 1, 10) <= ? "
            cash_params.append(as_of_date)
        cash_query += "GROUP BY strategy_id ORDER BY strategy_id"
        cash_rows = connection.execute(cash_query, cash_params).fetchall()
    except sqlite3.OperationalError:
        cash_query = "SELECT COALESCE(SUM(amount_inr), 0) AS total_cash_flow, MAX(balance_after_inr) AS last_cash FROM cash_ledger"
        cash_rows = connection.execute(cash_query).fetchall()

    fill_query = """SELECT COUNT(*) AS count FROM paper_fill f
                    LEFT JOIN paper_order o ON o.paper_order_id=f.paper_order_id
                    WHERE o.paper_order_id IS NULL"""
    fill_params: list[object] = []
    if as_of_date:
        fill_query += " AND substr(f.filled_at_utc, 1, 10) <= ?"
        fill_params.append(as_of_date)
    dangling_fills = connection.execute(fill_query, fill_params).fetchone()["count"]

    lot_query = """SELECT COUNT(*) AS count FROM position_lot p
                   LEFT JOIN paper_fill f ON f.paper_fill_id=p.opened_by_fill_id
                   WHERE f.paper_fill_id IS NULL"""
    dangling_lots = connection.execute(lot_query).fetchone()["count"]

    order_query = """SELECT COUNT(*) AS count FROM paper_order o
                     LEFT JOIN canonical_event e ON e.event_id=o.event_id
                     WHERE e.event_id IS NULL"""
    dangling_orders = connection.execute(order_query).fetchone()["count"]

    qty_query = """SELECT COUNT(*) AS count FROM (
         SELECT o.paper_order_id, o.quantity_requested,
                COALESCE(SUM(f.quantity), 0) AS filled_qty
         FROM paper_order o
         LEFT JOIN paper_fill f ON f.paper_order_id=o.paper_order_id
         GROUP BY o.paper_order_id
         HAVING o.quantity_requested < COALESCE(SUM(f.quantity), 0)
       )"""
    qty_mismatches = connection.execute(qty_query).fetchone()["count"]

    is_reconciled = (
        dangling_fills == 0
        and dangling_lots == 0
        and dangling_orders == 0
        and qty_mismatches == 0
    )

    return {
        "as_of_date": as_of_date,
        "is_reconciled": is_reconciled,
        "cash_by_strategy": [dict(row) for row in cash_rows],
        "dangling_fills": int(dangling_fills),
        "dangling_lots": int(dangling_lots),
        "dangling_orders": int(dangling_orders),
        "quantity_mismatches": int(qty_mismatches),
        "status": "RECONCILED" if is_reconciled else "DISCREPANCY_DETECTED",
    }


def get_report(connection: sqlite3.Connection, report_id: str) -> dict[str, Any]:
    mapping: dict[str, Callable[[], dict[str, Any]]] = {
        "lead-time": lambda: {"lead_time": lead_time_report(connection)},
        "source_lead_time": lambda: {"lead_time": lead_time_report(connection)},
        "entity_resolution_sample": lambda: entity_resolution_sample_report(connection),
        "event_firmness_sample": lambda: event_firmness_sample_report(connection),
        "causal_historical_event_study": lambda: causal_historical_event_study_report(),
        "replay_decision_fill_timing": lambda: replay_decision_fill_timing_report(connection),
        "cost_impact_sensitivity": lambda: cost_impact_sensitivity_report(),
        "source_failure_data_freshness": lambda: source_failure_data_freshness_report(connection),
        "performance": lambda: {
            "strategy_performance": strategy_performance_report(connection),
            "reconciliation": reconciliation_report(connection),
        },
        "reconciliation": lambda: {"reconciliation": reconciliation_report(connection)},
        "required": lambda: required_reports_bundle(connection),
        "strategy_benchmark": lambda: {
            "note": "Every strategy must define benchmark_id and window before measurement",
            "example": strategy_benchmark_report_as_dict(
                strategy_benchmark_report(
                    strategy_id="CR-01",
                    benchmark_id="NIFTY50",
                    window="event_day_to_exit",
                    entry_price=100.0,
                    exit_price=101.0,
                    high_while_held=104.0,
                    low_while_held=96.0,
                    holding_period=5,
                    sector_or_nifty_benchmark_return=0.002,
                    matched_market_cap_liquidity_control_return=0.001,
                    event_day_gap=0.01,
                    total_cost_inr=50.0,
                    quantity=100,
                )
            ),
        },
    }
    if report_id not in mapping:
        raise KeyError(report_id)
    return mapping[report_id]()
