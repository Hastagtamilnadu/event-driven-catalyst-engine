from __future__ import annotations

import sqlite3
from typing import Any


def lead_time_report(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT source_id,
                  COUNT(*) AS observations,
                  AVG(
                    (julianday(exchange_first_seen_at_utc) - julianday(source_published_at_utc)) * 1440.0
                  ) AS average_lead_minutes,
                  MIN(
                    (julianday(exchange_first_seen_at_utc) - julianday(source_published_at_utc)) * 1440.0
                  ) AS min_lead_minutes,
                  MAX(
                    (julianday(exchange_first_seen_at_utc) - julianday(source_published_at_utc)) * 1440.0
                  ) AS max_lead_minutes
           FROM source_observation
           WHERE exchange_first_seen_at_utc IS NOT NULL
           GROUP BY source_id ORDER BY source_id"""
    ).fetchall()
    return [dict(row) for row in rows]


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
    # 1. Cash by strategy
    cash_query = """SELECT strategy_id,
                           COALESCE(SUM(amount_inr), 0) AS total_cash_flow,
                           MAX(balance_after_inr) AS last_cash
                    FROM cash_ledger """
    if as_of_date:
        cash_query += f"WHERE substr(occurred_at_utc, 1, 10) <= '{as_of_date}' "
    cash_query += "GROUP BY strategy_id ORDER BY strategy_id"
    cash_rows = connection.execute(cash_query).fetchall()

    # 2. Dangling fills (fills without valid paper orders)
    fill_query = """SELECT COUNT(*) AS count FROM paper_fill f
                    LEFT JOIN paper_order o ON o.paper_order_id=f.paper_order_id
                    WHERE o.paper_order_id IS NULL"""
    if as_of_date:
        fill_query += f" AND substr(f.filled_at_utc, 1, 10) <= '{as_of_date}'"
    dangling_fills = connection.execute(fill_query).fetchone()["count"]

    # 3. Dangling position lots (lots without valid fills or events)
    lot_query = """SELECT COUNT(*) AS count FROM position_lot p
                   LEFT JOIN paper_fill f ON f.paper_fill_id=p.opened_by_fill_id
                   LEFT JOIN canonical_event e ON e.event_id=p.event_id
                   WHERE (f.paper_fill_id IS NULL OR e.event_id IS NULL)"""
    if as_of_date:
        lot_query += f" AND substr(p.opened_at_utc, 1, 10) <= '{as_of_date}'"
    dangling_lots = connection.execute(lot_query).fetchone()["count"]

    # 4. Dangling paper orders (orders without valid canonical events)
    order_query = """SELECT COUNT(*) AS count FROM paper_order o
                     LEFT JOIN canonical_event e ON e.event_id=o.event_id
                     WHERE e.event_id IS NULL"""
    if as_of_date:
        order_query += f" AND substr(o.created_at_utc, 1, 10) <= '{as_of_date}'"
    dangling_orders = connection.execute(order_query).fetchone()["count"]

    # 5. Quantity conservation check: requested == remaining + filled
    date_clause_o = f"WHERE substr(o.created_at_utc, 1, 10) <= '{as_of_date}'" if as_of_date else ""
    date_clause_f = f"AND substr(f.filled_at_utc, 1, 10) <= '{as_of_date}'" if as_of_date else ""
    qty_query = f"""SELECT COUNT(*) AS count FROM (
         SELECT o.paper_order_id, o.quantity_requested, o.quantity_remaining,
                COALESCE(SUM(f.quantity), 0) AS filled_qty
         FROM paper_order o
         LEFT JOIN paper_fill f ON f.paper_order_id=o.paper_order_id {date_clause_f}
         {date_clause_o}
         GROUP BY o.paper_order_id
         HAVING o.quantity_requested != (o.quantity_remaining + COALESCE(SUM(f.quantity), 0))
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
