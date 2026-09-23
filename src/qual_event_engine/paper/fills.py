from __future__ import annotations

"""§15 / §32.5 causal fill simulation.

For each chronologically ordered bar or quote:
1. Check whether order is valid, market is tradable, and data is complete.
2. Check price band, halt, surveillance, and participation constraints.
3. For a trigger order, trigger only using data after the trigger was created.
4. Estimate maximum fill quantity as floor(available_notional * participation_cap / candidate_price).
5. Apply spread and impact to candidate price.
6. Reject the quantity that breaches limit price, cash, or risk capacity.
7. Persist one paper_fill per filled quantity and update remaining order quantity atomically.
8. Continue until order expires or remaining quantity is zero.

Daily-only period: do not simulate an intraday trigger; mark INSUFFICIENT_INTRADAY_DATA.
Pre-open: fill only quantity supportable by actual auction turnover at equilibrium, capped by participation.
Partial fills are first-class outcomes.
"""

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from qual_event_engine.domain.enums import FillReason, OrderStatus
from qual_event_engine.domain.schemas import PaperFill
from qual_event_engine.paper.costs import calculate_equity_costs
from qual_event_engine.paper.impact import apply_slippage, calculate_market_impact_bps

INSUFFICIENT_INTRADAY_DATA = "INSUFFICIENT_INTRADAY_DATA"


@dataclass(frozen=True, slots=True)
class FillBar:
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume_shares: float
    turnover_inr: float
    is_complete: bool
    tradable: bool = True
    halted: bool = False
    surveillance_blocks_fill: bool = False
    price_band_pct: float | None = None
    reference_close: float | None = None
    auction_turnover_inr: float | None = None
    auction_equilibrium_price: float | None = None
    session: str = "INTRADAY"  # PRE_OPEN, INTRADAY, CLOSE


@dataclass
class FillOrderState:
    order_id: str
    symbol: str
    isin: str
    side: str
    quantity_requested: int
    quantity_remaining: int
    order_type: str
    limit_price: float | None
    trigger_price: float | None
    created_at_utc: datetime
    valid_until_utc: datetime
    participation_cap: float
    available_cash_inr: float
    risk_capacity_notional: float
    triggered: bool = False


@dataclass
class FillSimulationResult:
    fills: list[PaperFill] = field(default_factory=list)
    quantity_remaining: int = 0
    status: str = OrderStatus.PENDING.value
    reason: str = ""
    steps_executed: list[str] = field(default_factory=list)


class FillSimulator:
    """Simulates realistic order execution fills against market bars (§32.5)."""

    @classmethod
    def simulate_fill(
        cls,
        order_id: str,
        symbol: str,
        isin: str,
        side: str,
        requested_qty: int,
        bar_open: float,
        bar_volume: float,
        timestamp_utc: datetime | None = None,
    ) -> PaperFill:
        fill_id = str(uuid4())
        ts = timestamp_utc or datetime.now(UTC)
        impact_bps = calculate_market_impact_bps(requested_qty, bar_volume)
        fill_price = apply_slippage(bar_open, side, impact_bps)
        notional = fill_price * requested_qty
        costs = calculate_equity_costs(notional, side=side)
        return PaperFill(
            fill_id=fill_id,
            order_id=order_id,
            isin=isin,
            symbol=symbol.upper(),
            fill_price=round(fill_price, 2),
            fill_quantity=requested_qty,
            slippage_bps=round(impact_bps, 2),
            commission_inr=costs.brokerage_inr,
            stt_inr=costs.stt_inr,
            turnover_charges_inr=costs.exchange_charges_inr,
            gst_inr=costs.gst_inr,
            sebi_turnover_inr=costs.sebi_charges_inr,
            stamp_duty_inr=costs.stamp_duty_inr,
            total_cost_inr=costs.total_statutory_costs_inr,
            filled_at_utc=ts,
        )

    @classmethod
    def simulate_algorithm(
        cls,
        order: FillOrderState,
        bars: list[FillBar],
        connection: sqlite3.Connection | None = None,
        now_utc: datetime | None = None,
    ) -> FillSimulationResult:
        now = now_utc or datetime.now(UTC)
        result = FillSimulationResult(quantity_remaining=order.quantity_remaining)
        remaining = order.quantity_remaining
        cash = order.available_cash_inr
        steps: list[str] = []

        # Step 1: order valid
        if remaining <= 0 or order.quantity_requested <= 0:
            steps.append("1_order_invalid")
            result.steps_executed = steps
            result.status = OrderStatus.REJECTED.value
            result.reason = "ORDER_INVALID"
            return result
        if now > order.valid_until_utc:
            steps.append("1_order_expired")
            result.steps_executed = steps
            result.status = (
                OrderStatus.EXIT_UNFILLED.value
                if order.side.upper() == "SELL"
                else "EXPIRED"
            )
            result.reason = "ORDER_EXPIRED"
            return result

        is_trigger = order.trigger_price is not None or order.order_type.upper() in {
            "TRIGGER",
            "STOP",
            "STOP_LIMIT",
        }
        daily_only = all(b.interval.lower() in {"1d", "d", "day", "daily"} for b in bars) if bars else True
        if is_trigger and daily_only:
            steps.append("daily_only_intraday_trigger_blocked")
            result.steps_executed = steps
            result.status = INSUFFICIENT_INTRADAY_DATA
            result.reason = INSUFFICIENT_INTRADAY_DATA
            result.quantity_remaining = remaining
            return result

        ordered = sorted(bars, key=lambda b: b.close_time_utc)
        for bar in ordered:
            if remaining <= 0:
                break
            if bar.close_time_utc > order.valid_until_utc:
                steps.append("8_expired_during_walk")
                break

            # Step 1 continued: market tradable, data complete
            if not bar.is_complete or not bar.tradable:
                steps.append("1_data_incomplete_or_not_tradable")
                continue
            if bar.volume_shares <= 0 or bar.turnover_inr <= 0:
                steps.append("1_zero_volume")
                continue
            if bar.open <= 0 or bar.close <= 0:
                steps.append("1_data_incomplete")
                continue

            # Step 2: band, halt, surveillance, participation
            if bar.halted:
                steps.append("2_halt")
                continue
            if bar.surveillance_blocks_fill:
                steps.append("2_surveillance")
                continue
            if not cls._within_price_band(bar):
                steps.append("2_price_band")
                continue

            # Step 3: trigger only using data AFTER trigger was created
            candidate = cls._candidate_price(order, bar)
            if is_trigger:
                if bar.open_time_utc <= order.created_at_utc:
                    steps.append("3_bar_not_after_trigger_created")
                    continue
                if not order.triggered and not cls._trigger_crossed(order, bar):
                    steps.append("3_trigger_not_crossed")
                    continue
                order.triggered = True
                steps.append("3_trigger_armed")

            if candidate is None or candidate <= 0:
                steps.append("4_no_candidate_price")
                continue

            # Pre-open: auction turnover at equilibrium, participation-capped
            available_notional = bar.turnover_inr
            fill_reason = FillReason.INTRADAY_TRIGGER if is_trigger else FillReason.MARKET_OPEN
            if bar.session == "PRE_OPEN" or order.order_type.upper() == "MOO":
                eq = bar.auction_equilibrium_price or candidate
                candidate = eq
                available_notional = bar.auction_turnover_inr if bar.auction_turnover_inr is not None else 0.0
                fill_reason = FillReason.PRE_OPEN_AUCTION
                if available_notional <= 0:
                    steps.append("pre_open_no_auction_turnover")
                    continue

            # Step 4
            max_qty = math.floor(available_notional * order.participation_cap / candidate)
            qty = min(remaining, max(0, max_qty))
            steps.append("4_max_fill_qty")

            # Step 5: spread and impact
            impact_bps = calculate_market_impact_bps(qty, bar.volume_shares)
            fill_price = apply_slippage(candidate, order.side, impact_bps)
            steps.append("5_spread_impact")

            # Step 6: reject qty breaching limit, cash, risk capacity
            qty = cls._reject_breaches(order, qty, fill_price, cash)
            if qty <= 0:
                steps.append("6_qty_rejected")
                continue
            steps.append("6_qty_accepted")

            paper_fill = cls.simulate_fill(
                order_id=order.order_id,
                symbol=order.symbol,
                isin=order.isin,
                side=order.side,
                requested_qty=qty,
                bar_open=fill_price,
                bar_volume=bar.volume_shares,
                timestamp_utc=bar.close_time_utc,
            )
            # overwrite fill price to the impacted candidate (simulate_fill applies impact again)
            paper_fill = paper_fill.model_copy(
                update={
                    "fill_price": round(fill_price, 2),
                    "slippage_bps": round(impact_bps, 2),
                }
            )

            # Step 7: persist atomically when a connection is provided
            if connection is not None:
                cls._persist_fill_atomic(connection, order, paper_fill, remaining - qty, fill_reason.value)

            remaining -= qty
            notional = fill_price * qty
            if order.side.upper() == "BUY":
                cash -= notional + paper_fill.total_cost_inr
            else:
                cash += notional - paper_fill.total_cost_inr
            result.fills.append(paper_fill)
            steps.append("7_persisted_partial_or_full")

        result.quantity_remaining = remaining
        result.steps_executed = steps
        if remaining == 0:
            result.status = OrderStatus.FILLED.value
            result.reason = "FILLED"
        elif result.fills:
            result.status = OrderStatus.PARTIALLY_FILLED.value
            result.reason = "PARTIAL_FILL"
        elif now > order.valid_until_utc:
            result.status = (
                OrderStatus.EXIT_UNFILLED.value
                if order.side.upper() == "SELL"
                else "EXPIRED"
            )
            result.reason = "EXPIRED"
        else:
            result.status = OrderStatus.PENDING.value
            result.reason = "UNFILLED"
        steps.append("8_continue_until_expire_or_zero")
        result.steps_executed = steps
        return result

    @staticmethod
    def _within_price_band(bar: FillBar) -> bool:
        if bar.price_band_pct is None or bar.reference_close is None or bar.reference_close <= 0:
            return True
        cap = bar.price_band_pct / 100.0
        upper = bar.reference_close * (1.0 + cap)
        lower = bar.reference_close * (1.0 - cap)
        return lower <= bar.high and bar.low <= upper and lower <= bar.close <= upper

    @staticmethod
    def _candidate_price(order: FillOrderState, bar: FillBar) -> float | None:
        if bar.session == "PRE_OPEN" and bar.auction_equilibrium_price:
            return bar.auction_equilibrium_price
        if order.created_at_utc <= bar.open_time_utc:
            return bar.open
        return bar.close

    @staticmethod
    def _trigger_crossed(order: FillOrderState, bar: FillBar) -> bool:
        if order.trigger_price is None:
            return True
        trigger = order.trigger_price
        if order.side.upper() == "BUY":
            return bar.high >= trigger
        return bar.low <= trigger

    @staticmethod
    def _reject_breaches(
        order: FillOrderState, qty: int, fill_price: float, cash: float
    ) -> int:
        if qty <= 0 or fill_price <= 0:
            return 0
        if order.limit_price is not None:
            if order.side.upper() == "BUY" and fill_price > order.limit_price:
                return 0
            if order.side.upper() == "SELL" and fill_price < order.limit_price:
                return 0
        notional = fill_price * qty
        if order.side.upper() == "BUY":
            max_by_cash = math.floor(cash / fill_price) if fill_price > 0 else 0
            qty = min(qty, max(0, max_by_cash))
            notional = fill_price * qty
        if notional > order.risk_capacity_notional:
            qty = math.floor(order.risk_capacity_notional / fill_price)
        return max(0, qty)

    @staticmethod
    def _persist_fill_atomic(
        connection: sqlite3.Connection,
        order: FillOrderState,
        fill: PaperFill,
        new_remaining: int,
        fill_reason: str,
    ) -> None:
        nested = connection.in_transaction
        if not nested:
            connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO paper_fill(
              paper_fill_id, paper_order_id, filled_at_utc, quantity, raw_price,
              spread_cost_inr, impact_cost_inr, statutory_cost_inr, final_price,
              fill_reason, market_data_ref
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                fill.fill_id,
                fill.order_id,
                fill.filled_at_utc.isoformat(),
                fill.fill_quantity,
                fill.fill_price,
                0.0,
                fill.slippage_bps,
                fill.total_cost_inr,
                fill.fill_price,
                fill_reason,
                fill.order_id,
            ),
        )
        cols = {
            str(r[0])
            for r in connection.execute(
                "SELECT name FROM pragma_table_info(?)", ("paper_order",)
            ).fetchall()
        }
        status = OrderStatus.FILLED.value if new_remaining == 0 else OrderStatus.PARTIALLY_FILLED.value
        if "quantity_remaining" in cols:
            connection.execute(
                "UPDATE paper_order SET quantity_remaining=?, status=? WHERE paper_order_id=?",
                (new_remaining, status, order.order_id),
            )
        else:
            connection.execute(
                "UPDATE paper_order SET status=? WHERE paper_order_id=?",
                (status, order.order_id),
            )
        if not nested:
            connection.commit()
