from __future__ import annotations

"""§16 Sizing, capacity, and portfolio risk gates.

maximum_requested_notional =
  minimum(
    target_allocation_notional,
    risk_based_notional,
    participation_cap * ADT20,
    available_paper_cash
  )

Maximum intended position: 2.0% of paper NAV.
Sector: maximum 20% of paper NAV.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from qual_event_engine.config import RiskConfig
from qual_event_engine.decisions.risk import entry_gate
from qual_event_engine.research.reports import reconciliation_report

MAXIMUM_POSITION_NAV_PCT = 2.0
SECTOR_NAV_PCT = 20.0
DEFAULT_DATA_FRESHNESS_HOURS = 36.0

PORTFOLIO_CONTROLS = (
    "ISSUER",
    "SECTOR",
    "EVENT_CLUSTER",
    "DAILY_LOSS",
    "DRAWDOWN",
    "DATA_FRESHNESS",
    "RECONCILIATION",
    "INCIDENT",
)


@dataclass(frozen=True, slots=True)
class SizingResult:
    maximum_requested_notional: float
    target_allocation_notional: float
    risk_based_notional: float
    liquidity_notional: float
    available_paper_cash: float
    formula: str = (
        "min(target_allocation_notional, risk_based_notional, "
        "participation_cap * ADT20, available_paper_cash)"
    )


@dataclass(frozen=True, slots=True)
class RiskGateResult:
    passed: bool
    reason: str
    freeze_new_intents: bool
    controls_checked: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)


def maximum_requested_notional(
    paper_nav_inr: float,
    participation_cap: float,
    adt20_inr: float,
    available_paper_cash: float,
    risk_based_notional: float | None = None,
    target_allocation_nav_pct: float = MAXIMUM_POSITION_NAV_PCT,
) -> SizingResult:
    target = paper_nav_inr * (target_allocation_nav_pct / 100.0)
    risk_based = risk_based_notional if risk_based_notional is not None else target
    liquidity = participation_cap * adt20_inr
    requested = min(target, risk_based, liquidity, available_paper_cash)
    return SizingResult(
        maximum_requested_notional=max(0.0, requested),
        target_allocation_notional=target,
        risk_based_notional=risk_based,
        liquidity_notional=liquidity,
        available_paper_cash=available_paper_cash,
    )


class RiskGateManager:
    """Evaluates all eight §16.2 portfolio controls before order intent generation."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        risk_config: RiskConfig | None = None,
        paper_nav_inr: float = 1_000_000.0,
        drawdown_ladder_pct: tuple[float, ...] | None = None,
    ) -> None:
        self.connection = connection
        self.paper_nav_inr = (
            risk_config.paper_nav_inr if risk_config is not None else paper_nav_inr
        )
        self.sector_cap_pct = (
            risk_config.maximum_sector_nav_pct if risk_config is not None else SECTOR_NAV_PCT
        )
        self.daily_loss_freeze_pct = (
            risk_config.daily_loss_freeze_pct if risk_config is not None else 3.0
        )
        self.drawdown_ladder_pct = drawdown_ladder_pct or (
            (risk_config.drawdown_freeze_pct,) if risk_config is not None else (6.0, 9.0, 12.0)
        )
        self.issuer_nav_pct = MAXIMUM_POSITION_NAV_PCT

    def check_all_gates(self, event_row: sqlite3.Row) -> tuple[bool, str]:
        result = self.evaluate(event_row)
        return result.passed, result.reason

    def evaluate(self, event_row: sqlite3.Row) -> RiskGateResult:
        passed, reason = entry_gate(self.connection, event_row)
        if not passed:
            return RiskGateResult(
                False,
                f"ENTRY_GATE_FAILED: {reason}",
                freeze_new_intents=reason
                in {"OPEN_INCIDENT", "NEGATIVE_EVENT_BLACKLIST"},
                controls_checked=PORTFOLIO_CONTROLS,
            )

        symbol = str(event_row["symbol"])
        sector = event_row["sector"] if "sector" in tuple(event_row.keys()) else None
        cluster = str(event_row["event_type"]) if "event_type" in tuple(event_row.keys()) else None

        checks: list[tuple[str, RiskGateResult]] = [
            ("ISSUER", self._issuer_gate(symbol)),
            ("SECTOR", self._sector_gate(str(sector) if sector else None)),
            ("EVENT_CLUSTER", self._event_cluster_gate(cluster)),
            ("DAILY_LOSS", self._daily_loss_gate()),
            ("DRAWDOWN", self._drawdown_gate()),
            ("DATA_FRESHNESS", self._data_freshness_gate(symbol)),
            ("RECONCILIATION", self._reconciliation_gate()),
            ("INCIDENT", self._incident_gate()),
        ]
        for name, result in checks:
            if not result.passed:
                return RiskGateResult(
                    False,
                    f"{name}:{result.reason}",
                    freeze_new_intents=result.freeze_new_intents,
                    controls_checked=PORTFOLIO_CONTROLS,
                    details=result.details,
                )
        return RiskGateResult(
            True,
            "ALL_GATES_PASSED",
            freeze_new_intents=False,
            controls_checked=PORTFOLIO_CONTROLS,
        )

    def _exposure(self, where_sql: str, params: tuple[object, ...]) -> float:
        cols = self._columns("position_lot")
        price_col = "average_cost" if "average_cost" in cols else "avg_entry_price"
        sql = (
            "SELECT COALESCE(SUM(quantity_open * "
            + price_col
            + "), 0.0) FROM position_lot WHERE status IN ('OPEN','EXIT_REQUESTED','EXIT_UNFILLED') AND "
            + where_sql
        )
        row = self.connection.execute(sql, params).fetchone()
        return float(row[0]) if row else 0.0

    def _issuer_gate(self, symbol: str) -> RiskGateResult:
        exposure = self._exposure("symbol=?", (symbol,))
        cap = self.paper_nav_inr * (self.issuer_nav_pct / 100.0)
        if exposure >= cap:
            return RiskGateResult(
                False,
                "ISSUER_NAV_CAP",
                True,
                ("ISSUER",),
                {"exposure": exposure, "cap": cap, "formula_version": "16.1-v1"},
            )
        return RiskGateResult(True, "OK", False, ("ISSUER",), {"exposure": exposure, "cap": cap})

    def _sector_gate(self, sector: str | None) -> RiskGateResult:
        if not sector:
            return RiskGateResult(True, "SECTOR_UNKNOWN_NO_CAP_BYPASS", False, ("SECTOR",))
        cols = self._columns("canonical_event")
        if "sector" not in cols:
            return RiskGateResult(True, "SECTOR_FIELD_ABSENT", False, ("SECTOR",))
        lot_cols = self._columns("position_lot")
        price_col = "average_cost" if "average_cost" in lot_cols else "avg_entry_price"
        row = self.connection.execute(
            """
            SELECT COALESCE(SUM(p.quantity_open * p."""
            + price_col
            + """), 0.0)
            FROM position_lot p
            JOIN canonical_event e ON e.event_id = p.event_id
            WHERE p.status IN ('OPEN','EXIT_REQUESTED','EXIT_UNFILLED') AND e.sector = ?
            """,
            (sector,),
        )
        try:
            exposure = float(row.fetchone()[0])
        except sqlite3.OperationalError:
            exposure = 0.0
        cap = self.paper_nav_inr * (self.sector_cap_pct / 100.0)
        if exposure >= cap:
            return RiskGateResult(False, "SECTOR_20PCT_CAP", True, ("SECTOR",), {"exposure": exposure, "cap": cap})
        return RiskGateResult(True, "OK", False, ("SECTOR",), {"exposure": exposure, "cap": cap})

    def _event_cluster_gate(self, cluster: str | None) -> RiskGateResult:
        cap = self.paper_nav_inr * 0.10
        if not cluster:
            return RiskGateResult(True, "OK", False, ("EVENT_CLUSTER",), {"cap": cap})
        try:
            row = self.connection.execute(
                """
                SELECT COALESCE(SUM(p.quantity_open * p.average_cost), 0.0)
                FROM position_lot p
                JOIN canonical_event e ON e.event_id = p.event_id
                WHERE p.status IN ('OPEN','EXIT_REQUESTED','EXIT_UNFILLED') AND e.event_type = ?
                """,
                (cluster,),
            ).fetchone()
            exposure = float(row[0]) if row else 0.0
        except sqlite3.OperationalError:
            exposure = 0.0
        if exposure >= cap:
            return RiskGateResult(
                False,
                "EVENT_CLUSTER_CAP",
                True,
                ("EVENT_CLUSTER",),
                {"exposure": exposure, "cap": cap},
            )
        return RiskGateResult(True, "OK", False, ("EVENT_CLUSTER",), {"exposure": exposure, "cap": cap})

    def _daily_loss_gate(self) -> RiskGateResult:
        today = datetime.now(UTC).date().isoformat()
        pnl = self._session_pnl_since(today)
        threshold = -abs(self.paper_nav_inr * (self.daily_loss_freeze_pct / 100.0))
        if pnl <= threshold:
            return RiskGateResult(
                False,
                "DAILY_LOSS_FREEZE",
                True,
                ("DAILY_LOSS",),
                {"session_pnl": pnl, "threshold": threshold},
            )
        return RiskGateResult(True, "OK", False, ("DAILY_LOSS",), {"session_pnl": pnl})

    def _drawdown_gate(self) -> RiskGateResult:
        peak = self.paper_nav_inr
        nav = self._current_nav()
        dd_pct = ((peak - nav) / peak) * 100.0 if peak > 0 else 0.0
        freeze_level = self.drawdown_ladder_pct[-1] if self.drawdown_ladder_pct else 12.0
        if dd_pct >= freeze_level:
            return RiskGateResult(
                False,
                "DRAWDOWN_LADDER_FREEZE",
                True,
                ("DRAWDOWN",),
                {"drawdown_pct": dd_pct, "ladder": self.drawdown_ladder_pct},
            )
        derisk = [lvl for lvl in self.drawdown_ladder_pct if dd_pct >= lvl]
        return RiskGateResult(
            True,
            "DE_RISK" if derisk else "OK",
            False,
            ("DRAWDOWN",),
            {"drawdown_pct": dd_pct, "ladder_hit": derisk},
        )

    def _data_freshness_gate(self, symbol: str) -> RiskGateResult:
        cutoff = (datetime.now(UTC) - timedelta(hours=DEFAULT_DATA_FRESHNESS_HOURS)).isoformat()
        stale: list[str] = []
        price = self.connection.execute(
            """
            SELECT MAX(close_time_utc) FROM price_bar WHERE symbol=? AND is_complete=1
            """,
            (symbol,),
        ).fetchone()
        if not price or not price[0] or str(price[0]) < cutoff:
            stale.append("price")
        membership = self.connection.execute(
            """
            SELECT 1 FROM security_membership
            WHERE symbol=? AND effective_from_utc<=?
              AND (effective_to_utc IS NULL OR effective_to_utc>?)
            LIMIT 1
            """,
            (symbol, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
        ).fetchone()
        if not membership:
            stale.append("universe")
        band = self.connection.execute(
            """
            SELECT price_band_pct, surveillance_status FROM security_membership
            WHERE symbol=? ORDER BY effective_from_utc DESC LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        if not band or band["price_band_pct"] is None:
            stale.append("band")
        if not band or band["surveillance_status"] is None:
            stale.append("surveillance")
        src = self.connection.execute(
            "SELECT MAX(system_first_seen_at_utc) FROM source_observation"
        ).fetchone()
        if not src or not src[0] or str(src[0]) < cutoff:
            stale.append("source")
        if stale:
            return RiskGateResult(
                False,
                "STALE_DATA:" + ",".join(stale),
                True,
                ("DATA_FRESHNESS",),
                {"stale": stale},
            )
        return RiskGateResult(True, "OK", False, ("DATA_FRESHNESS",))

    def _reconciliation_gate(self) -> RiskGateResult:
        report = reconciliation_report(self.connection)
        if not report.get("is_reconciled", True):
            return RiskGateResult(
                False,
                "RECONCILIATION_MISMATCH",
                True,
                ("RECONCILIATION",),
                {"report": report},
            )
        return RiskGateResult(True, "OK", False, ("RECONCILIATION",))

    def _incident_gate(self) -> RiskGateResult:
        row = self.connection.execute(
            "SELECT 1 FROM incident WHERE status='OPEN' LIMIT 1"
        ).fetchone()
        if row:
            return RiskGateResult(False, "OPEN_INCIDENT", True, ("INCIDENT",))
        return RiskGateResult(True, "OK", False, ("INCIDENT",))

    def _session_pnl_since(self, day_iso: str) -> float:
        try:
            row = self.connection.execute(
                """
                SELECT COALESCE(SUM(amount_inr), 0.0) FROM cash_ledger
                WHERE occurred_at_utc >= ? AND entry_type IN ('FILL','MARK','PNL')
                """,
                (day_iso,),
            ).fetchone()
            return float(row[0]) if row else 0.0
        except sqlite3.OperationalError:
            return 0.0

    def _current_nav(self) -> float:
        cash_row = self.connection.execute(
            "SELECT balance_after_inr FROM cash_ledger ORDER BY occurred_at_utc DESC, rowid DESC LIMIT 1"
        ).fetchone()
        cash = float(cash_row[0]) if cash_row else self.paper_nav_inr
        pos = self._exposure("1=1", ())
        return cash + pos

    def _columns(self, table: str) -> set[str]:
        return {
            str(r[0])
            for r in self.connection.execute(
                "SELECT name FROM pragma_table_info(?)", (table,)
            ).fetchall()
        }
