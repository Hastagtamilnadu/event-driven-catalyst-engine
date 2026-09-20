from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from qual_event_engine.domain.enums import PositionStatus


@dataclass
class PositionLot:
    lot_id: str
    strategy_id: str
    symbol: str
    isin: str
    quantity_open: int
    quantity_initial: int
    entry_price: float
    opened_at_utc: datetime
    status: PositionStatus = PositionStatus.OPEN


class PositionManager:
    """Tracks position lots, FIFO depletion on sell fills, and calculates PnL."""

    def __init__(self) -> None:
        self._lots: list[PositionLot] = []

    def add_lot(
        self,
        strategy_id: str,
        symbol: str,
        isin: str,
        quantity: int,
        entry_price: float,
        timestamp_utc: datetime | None = None,
    ) -> PositionLot:
        lot = PositionLot(
            lot_id=str(uuid4()),
            strategy_id=strategy_id,
            symbol=symbol.upper(),
            isin=isin,
            quantity_open=quantity,
            quantity_initial=quantity,
            entry_price=entry_price,
            opened_at_utc=timestamp_utc or datetime.now(UTC),
        )
        self._lots.append(lot)
        return lot

    def close_lots_fifo(
        self,
        strategy_id: str,
        symbol: str,
        quantity_to_close: int,
        exit_price: float,
    ) -> tuple[float, int]:
        """Closes lots FIFO. Returns (realized_pnl_inr, remaining_unclosed_qty)."""
        qty_left = quantity_to_close
        realized_pnl = 0.0

        for lot in self._lots:
            if lot.strategy_id == strategy_id and lot.symbol == symbol.upper() and lot.status == PositionStatus.OPEN:
                deplete = min(lot.quantity_open, qty_left)
                lot_pnl = (exit_price - lot.entry_price) * deplete
                realized_pnl += lot_pnl
                lot.quantity_open -= deplete
                qty_left -= deplete
                if lot.quantity_open == 0:
                    lot.status = PositionStatus.CLOSED
                if qty_left <= 0:
                    break

        return realized_pnl, qty_left

    def get_open_positions(self, strategy_id: str | None = None) -> list[PositionLot]:
        lots = [l for l in self._lots if l.status == PositionStatus.OPEN]
        if strategy_id:
            lots = [l for l in lots if l.strategy_id == strategy_id]
        return lots
