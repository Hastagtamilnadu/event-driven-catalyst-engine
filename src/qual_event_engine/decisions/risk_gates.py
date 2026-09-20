from __future__ import annotations

import sqlite3

from qual_event_engine.decisions.risk import entry_gate


class RiskGateManager:
    """Evaluates all deterministic risk gates prior to order intent generation."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def check_all_gates(self, event_row: sqlite3.Row) -> tuple[bool, str]:
        # 1. Entry gate (incident, universe, surveillance, price band, blacklist)
        passed, reason = entry_gate(self.connection, event_row)
        if not passed:
            return False, f"ENTRY_GATE_FAILED: {reason}"

        # 2. Maximum single-stock concentration check (e.g. max 10% of portfolio)
        symbol = event_row["symbol"]
        pos_cur = self.connection.execute(
            """
            SELECT COALESCE(SUM(quantity_open * avg_entry_price), 0.0)
            FROM position_lot
            WHERE symbol = ? AND status = 'OPEN'
            """,
            (symbol,),
        )
        current_sym_exposure = float(pos_cur.fetchone()[0])
        if current_sym_exposure > 500_000.0:  # Example 5L INR cap
            return False, f"CONCENTRATION_LIMIT_EXCEEDED: current exposure {current_sym_exposure}"

        return True, "ALL_GATES_PASSED"
