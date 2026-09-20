from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from qual_event_engine.domain.schemas import PaperFill
from qual_event_engine.paper.costs import calculate_equity_costs
from qual_event_engine.paper.impact import apply_slippage, calculate_market_impact_bps


class FillSimulator:
    """Simulates realistic order execution fills against market bars."""

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

        # Calculate impact and fill price
        impact_bps = calculate_market_impact_bps(requested_qty, bar_volume)
        fill_price = apply_slippage(bar_open, side, impact_bps)
        notional = fill_price * requested_qty

        # Calculate costs
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
