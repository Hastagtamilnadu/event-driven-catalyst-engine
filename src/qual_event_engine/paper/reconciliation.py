from __future__ import annotations

import sqlite3

from qual_event_engine.domain.schemas import ReconciliationResult


class PortfolioReconciler:
    """Performs end-of-day portfolio reconciliation across cash, orders, fills, and lots."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def reconcile_date(self, target_date: str) -> ReconciliationResult:
        discrepancies: list[str] = []

        # 1. Check dangling orders (orders stuck in PENDING or SUBMITTED across days)
        dang_cur = self.connection.execute(
            """
            SELECT COUNT(*) FROM paper_order
            WHERE status IN ('PENDING', 'SUBMITTED', 'PENDING_PRICE')
              AND created_at_utc < ?
            """,
            (f"{target_date}T23:59:59",),
        )
        dangling_count = int(dang_cur.fetchone()[0])
        if dangling_count > 0:
            discrepancies.append(f"Found {dangling_count} dangling orders")

        # 2. Check unfilled orders
        unfilled_cur = self.connection.execute(
            """
            SELECT COUNT(*) FROM paper_order
            WHERE status = 'PARTIALLY_FILLED'
              AND created_at_utc <= ?
            """,
            (f"{target_date}T23:59:59",),
        )
        unfilled_count = int(unfilled_cur.fetchone()[0])

        # 3. Check open positions
        pos_cur = self.connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(quantity_open * avg_entry_price), 0.0)
            FROM position_lot
            WHERE status = 'OPEN'
            """
        )
        pos_row = pos_cur.fetchone()
        open_pos_count = int(pos_row[0])
        pos_value = float(pos_row[1])

        # 4. Check cash balance
        cash_cur = self.connection.execute(
            """
            SELECT balance_after_inr FROM cash_ledger
            ORDER BY occurred_at_utc DESC, rowid DESC
            LIMIT 1
            """
        )
        cash_row = cash_cur.fetchone()
        cash_balance = float(cash_row[0]) if cash_row else 10_000_000.0  # Default 1 Cr NAV

        from typing import Literal

        nav = cash_balance + pos_value
        status: Literal["RECONCILED", "DISCREPANCY_DETECTED"] = "DISCREPANCY_DETECTED" if discrepancies else "RECONCILED"

        return ReconciliationResult(
            reconciliation_date=target_date,
            status=status,
            dangling_orders_count=dangling_count,
            unfilled_orders_count=unfilled_count,
            open_positions_count=open_pos_count,
            cash_balance_inr=cash_balance,
            nav_inr=nav,
            discrepancies=discrepancies,
        )
