from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from qual_event_engine.domain.enums import OrderSide, OrderType


@dataclass(frozen=True, slots=True)
class OrderIntent:
    paper_order_id: str
    client_order_id: str
    event_id: str
    strategy_id: str
    symbol: str
    isin: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    limit_price: float | None
    created_at_utc: datetime


class OrderManager:
    """Manages paper order sizing, lifecycle, and order state tracking."""

    @staticmethod
    def calculate_order_quantity(
        nav_inr: float,
        target_allocation_pct: float,
        current_price: float,
        adt20_shares: float | None = None,
        max_participation_pct: float = 10.0,
    ) -> int:
        if current_price <= 0:
            return 0
        target_notional = nav_inr * (target_allocation_pct / 100.0)
        qty = int(target_notional / current_price)

        if adt20_shares and adt20_shares > 0:
            max_qty_liquidity = int(adt20_shares * (max_participation_pct / 100.0))
            qty = min(qty, max_qty_liquidity)

        return max(0, qty)

    @classmethod
    def create_order(
        cls,
        event_id: str,
        strategy_id: str,
        symbol: str,
        isin: str,
        side: OrderSide,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: float | None = None,
    ) -> OrderIntent:
        order_id = str(uuid4())
        client_order_id = f"ORD-{strategy_id}-{symbol}-{order_id[:8]}"
        return OrderIntent(
            paper_order_id=order_id,
            client_order_id=client_order_id,
            event_id=event_id,
            strategy_id=strategy_id,
            symbol=symbol.upper(),
            isin=isin,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            created_at_utc=datetime.now(UTC),
        )
