from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorporateAction:
    symbol: str
    action_type: str
    ex_date: str
    adjustment_factor: float
    source_id: str
    isin: str | None = None


class CorporateActionManager:
    """Manages corporate action adjustments for prices and share counts."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_actions(self, symbol: str, start_date: str | None = None, end_date: str | None = None) -> list[CorporateAction]:
        query = """
            SELECT symbol, action_type, ex_date, adjustment_factor, source_id, isin
            FROM corporate_actions
            WHERE symbol = ?
        """
        params: list[str] = [symbol.upper()]
        if start_date:
            query += " AND ex_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND ex_date <= ?"
            params.append(end_date)
        query += " ORDER BY ex_date ASC"

        cursor = self.connection.execute(query, params)
        rows = cursor.fetchall()
        return [
            CorporateAction(
                symbol=r[0],
                action_type=r[1],
                ex_date=r[2],
                adjustment_factor=float(r[3]),
                source_id=r[4],
                isin=r[5],
            )
            for r in rows
        ]

    def get_cumulative_adjustment_factor(self, symbol: str, from_date: str, to_date: str) -> float:
        actions = self.get_actions(symbol, start_date=from_date, end_date=to_date)
        factor = 1.0
        for a in actions:
            factor *= a.adjustment_factor
        return factor
