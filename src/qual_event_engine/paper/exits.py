from __future__ import annotations

"""§17 Negative events and exit policy / §32.6 exit algorithm.

§32.6 at every end-of-bar/end-of-day evaluation:
1. Evaluate the strategy-specific stop, target, time, and negative-event policies.
2. If more than one policy triggers within an ambiguous daily bar, select the adverse feasible sequence.
3. Create a SELL paper order; do not close the position yet.
4. Apply normal fill rules.
5. Preserve remaining quantity, mark EXIT_UNFILLED when expiration occurs.

§17:
1. Detect and evidence the adverse event.
2. Map it to open paper positions.
3. Change position to EXIT_REQUESTED and apply the strategy blacklist.
4. Attempt exit using the same realistic fill rules as entry.
5. Preserve unfilled exposure when a band, halt, or lack of bids prevents execution.
6. Record actual gross/net exposure until a fill occurs.

Default blacklist: 20 trading sessions.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from qual_event_engine.domain.enums import OrderStatus, PositionStatus
from qual_event_engine.market.calendar import TradingCalendar
from qual_event_engine.paper.fills import FillBar, FillOrderState, FillSimulator

DEFAULT_BLACKLIST_SESSIONS = 20
EXIT_REQUESTED = PositionStatus.EXIT_REQUESTED.value
EXIT_UNFILLED = OrderStatus.EXIT_UNFILLED.value


@dataclass(frozen=True, slots=True)
class ExitTrigger:
    should_exit: bool
    reason: str
    exit_price: float | None = None
    policies_triggered: tuple[str, ...] = ()
    adverse_sequence_selected: bool = False


@dataclass(frozen=True, slots=True)
class ExitOrderIntent:
    side: str
    quantity: int
    reason: str
    position_closed: bool
    status: str


class ExitEvaluator:
    """Stop, target, time, gap/circuit, and negative-event exits (§32.6, §17)."""

    @classmethod
    def evaluate_exit(
        cls,
        entry_price: float,
        current_price: float,
        stop_loss_pct: float,
        holding_sessions: int,
        max_time_stop_sessions: int,
        target_return_pct: float | None = None,
    ) -> ExitTrigger:
        if entry_price <= 0:
            return ExitTrigger(should_exit=False, reason="NONE")

        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
        if pnl_pct <= -abs(stop_loss_pct):
            return ExitTrigger(
                should_exit=True,
                reason=f"STOP_LOSS_HIT: return {pnl_pct:.2f}% <= -{stop_loss_pct}%",
                exit_price=current_price,
                policies_triggered=("STOP",),
            )
        if target_return_pct and pnl_pct >= target_return_pct:
            return ExitTrigger(
                should_exit=True,
                reason=f"TARGET_REACHED: return {pnl_pct:.2f}% >= {target_return_pct}%",
                exit_price=current_price,
                policies_triggered=("TARGET",),
            )
        if holding_sessions >= max_time_stop_sessions:
            return ExitTrigger(
                should_exit=True,
                reason=(
                    f"TIME_STOP_EXPIRED: holding {holding_sessions} sessions"
                    f" >= {max_time_stop_sessions}"
                ),
                exit_price=current_price,
                policies_triggered=("TIME",),
            )
        return ExitTrigger(should_exit=False, reason="NONE")

    @classmethod
    def evaluate_end_of_bar(
        cls,
        entry_price: float,
        bar: FillBar,
        stop_loss_pct: float,
        target_return_pct: float | None,
        holding_sessions: int,
        max_time_stop_sessions: int,
        negative_event: bool = False,
        side: str = "LONG",
    ) -> ExitTrigger:
        """§32.6 steps 1–2 including adverse sequence on ambiguous daily OHLC."""
        stop_price = entry_price * (1.0 - abs(stop_loss_pct) / 100.0)
        target_price = (
            entry_price * (1.0 + abs(target_return_pct) / 100.0) if target_return_pct else None
        )
        stop_hit = bar.low <= stop_price
        target_hit = target_price is not None and bar.high >= target_price
        time_hit = holding_sessions >= max_time_stop_sessions
        policies: list[str] = []
        if stop_hit:
            policies.append("STOP")
        if target_hit:
            policies.append("TARGET")
        if time_hit:
            policies.append("TIME")
        if negative_event:
            policies.append("NEGATIVE_EVENT")

        if not policies:
            return ExitTrigger(should_exit=False, reason="NONE", exit_price=bar.close)

        ambiguous = bar.interval.lower() in {"1d", "d", "day", "daily"} and len(policies) > 1
        selected = policies[0]
        exit_price = bar.close
        if ambiguous:
            # Adverse feasible sequence for a long: stop before target (worse outcome).
            if side.upper() in {"LONG", "BUY"} and "STOP" in policies:
                selected = "STOP"
                exit_price = min(bar.open, stop_price, bar.close)
            elif side.upper() in {"SHORT", "SELL"} and "STOP" in policies:
                selected = "STOP"
                stop_short = entry_price * (1.0 + abs(stop_loss_pct) / 100.0)
                exit_price = max(bar.open, stop_short, bar.close)
            elif "NEGATIVE_EVENT" in policies:
                selected = "NEGATIVE_EVENT"
                exit_price = bar.close
            else:
                selected = "TIME"
                exit_price = bar.close
        elif selected == "STOP":
            locked = bar.high == bar.low
            if locked:
                exit_price = bar.close  # gap/circuit: first realistically eligible print
            else:
                exit_price = stop_price
        elif selected == "TARGET" and target_price is not None:
            exit_price = target_price
        elif selected == "NEGATIVE_EVENT":
            exit_price = bar.close

        if bar.halted:
            return ExitTrigger(
                should_exit=True,
                reason="HALTED_UNFILLED_EXPOSURE_PRESERVED",
                exit_price=None,
                policies_triggered=tuple(policies),
                adverse_sequence_selected=ambiguous,
            )

        return ExitTrigger(
            should_exit=True,
            reason=selected,
            exit_price=exit_price,
            policies_triggered=tuple(policies),
            adverse_sequence_selected=ambiguous,
        )

    @classmethod
    def create_sell_order(
        cls,
        quantity_open: int,
        reason: str,
        bar: FillBar | None = None,
        order: FillOrderState | None = None,
    ) -> ExitOrderIntent:
        """§32.6 steps 3–5: create SELL, apply fill rules, do not close yet."""
        if quantity_open <= 0:
            return ExitOrderIntent("SELL", 0, reason, False, EXIT_UNFILLED)
        if bar is not None and (bar.halted or not bar.tradable or bar.volume_shares <= 0):
            return ExitOrderIntent("SELL", quantity_open, reason, False, EXIT_UNFILLED)
        if order is not None and bar is not None:
            sim = FillSimulator.simulate_algorithm(order, [bar])
            remaining = sim.quantity_remaining
            status = sim.status if remaining == 0 else (
                OrderStatus.PARTIALLY_FILLED.value if sim.fills else EXIT_UNFILLED
            )
            if status == "EXPIRED":
                status = EXIT_UNFILLED
            return ExitOrderIntent("SELL", remaining, reason, False, status)
        return ExitOrderIntent("SELL", quantity_open, reason, False, "PENDING_EXIT")

    @classmethod
    def apply_negative_event_exit(
        cls,
        connection: sqlite3.Connection,
        event_id: str,
        symbol: str,
        evidence: str,
        sessions: int = DEFAULT_BLACKLIST_SESSIONS,
        now_utc: datetime | None = None,
    ) -> dict[str, int]:
        """§17 full path: evidence → map positions → EXIT_REQUESTED → blacklist → fill attempt."""
        now = now_utc or datetime.now(UTC)
        if not evidence.strip():
            return {"positions_mapped": 0, "exit_orders": 0, "blacklisted": 0}

        lots = connection.execute(
            "SELECT * FROM position_lot WHERE symbol=? AND status='OPEN'",
            (symbol,),
        ).fetchall()
        ends = _blacklist_end(now, sessions)
        connection.execute(
            """
            INSERT INTO blacklist(blacklist_id,symbol,reason_event_id,starts_at_utc,ends_at_utc,status)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(symbol,reason_event_id) DO NOTHING
            """,
            (str(uuid4()), symbol, event_id, now.isoformat(), ends.isoformat(), "ACTIVE"),
        )
        exit_orders = 0
        for lot in lots:
            connection.execute(
                "UPDATE position_lot SET status=? WHERE position_lot_id=?",
                (EXIT_REQUESTED, lot["position_lot_id"]),
            )
            already = connection.execute(
                """
                SELECT 1 FROM paper_order
                WHERE symbol=? AND side='SELL'
                  AND status IN ('PENDING_EXIT','PENDING_PRICE','PARTIALLY_FILLED')
                  AND strategy_id=?
                """,
                (symbol, lot["strategy_id"]),
            ).fetchone()
            if already:
                continue
            qty = int(lot["quantity_open"])
            connection.execute(
                """
                INSERT INTO paper_order(
                  paper_order_id,client_order_id,event_id,strategy_id,strategy_version,symbol,isin,side,
                  quantity_requested,order_type,limit_price,trigger_price,participation_cap,
                  valid_from_utc,valid_until_utc,status,decision_snapshot_hash,created_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid4()),
                    f"{lot['position_lot_id']}:NEGATIVE:{event_id}",
                    event_id,
                    lot["strategy_id"],
                    "1",
                    symbol,
                    lot["isin"],
                    "SELL",
                    qty,
                    "MARKET",
                    None,
                    None,
                    1.0,
                    now.isoformat(),
                    (now + timedelta(days=5)).isoformat(),
                    "PENDING_EXIT",
                    event_id,
                    now.isoformat(),
                ),
            )
            exit_orders += 1
        return {
            "positions_mapped": len(lots),
            "exit_orders": exit_orders,
            "blacklisted": 1,
            "blacklist_sessions": sessions,
        }

    @classmethod
    def mark_exit_unfilled(cls, connection: sqlite3.Connection, paper_order_id: str) -> None:
        connection.execute(
            "UPDATE paper_order SET status=? WHERE paper_order_id=?",
            (EXIT_UNFILLED, paper_order_id),
        )
        row = connection.execute(
            "SELECT symbol, strategy_id FROM paper_order WHERE paper_order_id=?",
            (paper_order_id,),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE position_lot SET status=?
                WHERE symbol=? AND strategy_id=? AND status=?
                """,
                (PositionStatus.EXIT_UNFILLED.value, row["symbol"], row["strategy_id"], EXIT_REQUESTED),
            )


def _blacklist_end(now: datetime, sessions: int) -> datetime:
    d = now.date()
    remaining = max(1, sessions)
    # Advance by trading sessions, not calendar days.
    cursor = d
    while remaining > 0:
        cursor = TradingCalendar.next_trading_day(cursor)
        remaining -= 1
    return datetime.combine(cursor, datetime.min.time(), tzinfo=UTC)
