from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from qual_event_engine.domain.models import StrategyConfig
from qual_event_engine.persistence.repositories import utc_now


class MarketBar(BaseModel):
    symbol: str
    isin: str | None = None
    interval: str = "1m"
    open_time_utc: datetime
    close_time_utc: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume_shares: float = Field(ge=0)
    turnover_inr: float = Field(ge=0)
    is_complete: bool = True
    source_id: str


def import_market_bars(connection: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(f"Market-bar JSONL file not found: {path}")
    inserted = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                bar = MarketBar.model_validate(json.loads(line))
            except Exception as exc:
                raise ValueError(f"Invalid market bar at {path}:{line_number}: {exc}") from exc
            result = connection.execute(
                """INSERT INTO price_bar(
                  bar_id,isin,symbol,interval,open_time_utc,close_time_utc,open,high,low,close,
                  volume_shares,turnover_inr,is_complete,source_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,interval,open_time_utc,source_id) DO NOTHING""",
                (
                    str(uuid4()),
                    bar.isin,
                    bar.symbol.upper(),
                    bar.interval,
                    bar.open_time_utc.astimezone(UTC).isoformat(),
                    bar.close_time_utc.astimezone(UTC).isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume_shares,
                    bar.turnover_inr,
                    int(bar.is_complete),
                    bar.source_id,
                ),
            )
            inserted += result.rowcount
    return inserted


def _balance(connection: sqlite3.Connection, strategy_id: str, paper_nav_inr: float) -> float:
    row = connection.execute(
        """SELECT balance_after_inr FROM cash_ledger
           WHERE strategy_id=? ORDER BY occurred_at_utc DESC, rowid DESC LIMIT 1""",
        (strategy_id,),
    ).fetchone()
    return float(row["balance_after_inr"]) if row else paper_nav_inr


def _record_cash(
    connection: sqlite3.Connection,
    strategy_id: str,
    reference_id: str,
    amount_inr: float,
    balance_after: float,
) -> None:
    connection.execute(
        """INSERT INTO cash_ledger(
          cash_entry_id,strategy_id,occurred_at_utc,entry_type,reference_id,amount_inr,balance_after_inr
        ) VALUES(?,?,?,?,?,?,?)""",
        (str(uuid4()), strategy_id, utc_now(), "FILL", reference_id, amount_inr, balance_after),
    )


def _costs(notional: float, participation_fraction: float, side: str = "BUY") -> tuple[float, float, float]:
    """Computes Indian equity transaction costs according to Section 23 and costs.yaml:
    - STT: 0.10% delivery buy & sell
    - Exchange turnover charges: 0.00325%
    - SEBI charges: 0.00010%
    - Stamp duty: 0.015% buy only
    - GST: 18% on exchange and SEBI charges
    - Half-spread: 5 bps
    - Market impact: 5 bps + participation penalty
    """
    stt = notional * 0.0010
    exchange_charges = notional * 0.0000325
    sebi_charges = notional * 0.0000010
    stamp_duty = notional * 0.00015 if side == "BUY" else 0.0
    gst = (exchange_charges + sebi_charges) * 0.18
    statutory = stt + exchange_charges + sebi_charges + stamp_duty + gst

    spread = notional * 0.0005
    impact = notional * (0.0005 + min(0.02, math.sqrt(max(participation_fraction, 0.0)) * 0.01))
    return spread, impact, statutory


def _latest_fillable_bar(
    connection: sqlite3.Connection, symbol: str, valid_from_utc: str, valid_until_utc: str
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = connection.execute(
        """SELECT * FROM price_bar
           WHERE symbol=? AND is_complete=1 AND close_time_utc>=? AND close_time_utc<=?
           ORDER BY close_time_utc ASC LIMIT 1""",
        (symbol, valid_from_utc, valid_until_utc),
    ).fetchone()
    return row


def process_pending_orders(
    connection: sqlite3.Connection,
    strategies: dict[str, StrategyConfig],
    paper_nav_inr: float,
    as_of_utc: str | None = None,
) -> dict[str, int]:
    stats = {"filled": 0, "partially_filled": 0, "expired": 0, "unfilled": 0, "exit_unfilled": 0}
    now = as_of_utc or datetime.now(UTC).isoformat()
    orders = connection.execute(
        """SELECT * FROM paper_order WHERE status IN ('PENDING_PRICE','PENDING_EXIT','PARTIALLY_FILLED')
           ORDER BY created_at_utc"""
    ).fetchall()

    for order in orders:
        is_exit = order["side"] == "SELL" or order["status"] == "PENDING_EXIT"

        # Check expiration
        if order["valid_until_utc"] < now:
            new_status = "EXIT_UNFILLED" if is_exit else "EXPIRED"
            connection.execute(
                "UPDATE paper_order SET status=? WHERE paper_order_id=?",
                (new_status, order["paper_order_id"]),
            )
            if is_exit:
                stats["exit_unfilled"] += 1
            else:
                stats["expired"] += 1
            continue

        bar = _latest_fillable_bar(
            connection,
            order["symbol"],
            order["valid_from_utc"],
            order["valid_until_utc"],
        )

        # Halt handling / zero liquidity handling (§32.5)
        if not bar or float(bar["turnover_inr"]) <= 0 or float(bar["volume_shares"]) <= 0:
            stats["unfilled"] += 1
            continue

        # Lower Circuit Detection for SELL exits (§32.6, §34.2):
        # In a lower circuit, High == Low and bids are absent, so exits cannot fill
        is_lower_circuit = (
            float(bar["high"]) == float(bar["low"])
            and float(bar["close"]) <= float(bar["open"])
            and float(bar["volume_shares"]) < 100  # negligible volume
        )
        if is_exit and is_lower_circuit:
            # Cannot execute sell in a locked lower circuit
            stats["unfilled"] += 1
            continue

        config = strategies.get(order["strategy_id"])
        if not config:
            connection.execute(
                "UPDATE paper_order SET status='REJECTED_CONFIG' WHERE paper_order_id=?",
                (order["paper_order_id"],),
            )
            continue

        # Gap Opening Model (§32.5):
        # If order was created prior to bar open, candidate price is the opening gap price
        is_gap_order = order["created_at_utc"] <= bar["open_time_utc"]
        raw_price = float(bar["open"]) if is_gap_order else float(bar["close"])

        # Check limit / trigger constraints
        if order["limit_price"] is not None:
            limit = float(order["limit_price"])
            if order["side"] == "BUY" and raw_price > limit:
                stats["unfilled"] += 1
                continue
            if order["side"] == "SELL" and raw_price < limit:
                stats["unfilled"] += 1
                continue

        cash = _balance(connection, order["strategy_id"], paper_nav_inr)
        max_position = paper_nav_inr * config.maximum_position_nav_pct / 100
        max_by_cash = cash if order["side"] == "BUY" else float("inf")
        requested_notional = min(max_position, max_by_cash)

        # Capacity & participation cap (§32.5): floor(available_turnover * participation_cap / candidate_price)
        participation_cap = float(order["participation_cap_pct"]) / 100.0
        max_by_liquidity = float(bar["turnover_inr"]) * participation_cap
        notional_capacity = min(requested_notional, max_by_liquidity)
        max_qty_by_liquidity = int(notional_capacity // raw_price)

        remaining_qty = int(order["quantity_remaining"])
        quantity = min(remaining_qty, max_qty_by_liquidity)

        if order["side"] == "SELL":
            lot = connection.execute(
                """SELECT position_lot_id, quantity_open FROM position_lot
                   WHERE strategy_id=? AND symbol=? AND status='OPEN'
                   ORDER BY opened_at_utc LIMIT 1""",
                (order["strategy_id"], order["symbol"]),
            ).fetchone()
            if not lot:
                connection.execute(
                    "UPDATE paper_order SET status='CANCELLED_NO_POSITION' WHERE paper_order_id=?",
                    (order["paper_order_id"],),
                )
                continue
            quantity = min(quantity, int(lot["quantity_open"]))

        if quantity <= 0:
            stats["unfilled"] += 1
            continue

        raw_notional = quantity * raw_price
        participation = raw_notional / float(bar["turnover_inr"])
        spread, impact, statutory = _costs(raw_notional, participation, side=order["side"])
        final_price = (
            raw_price + (spread + impact + statutory) / quantity
            if order["side"] == "BUY"
            else raw_price - (spread + impact + statutory) / quantity
        )

        fill_id = str(uuid4())
        connection.execute(
            """INSERT INTO paper_fill(
              paper_fill_id,paper_order_id,filled_at_utc,quantity,raw_price,spread_cost_inr,
              impact_cost_inr,statutory_cost_inr,final_price,fill_reason,market_data_ref
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fill_id,
                order["paper_order_id"],
                bar["close_time_utc"],
                quantity,
                raw_price,
                spread,
                impact,
                statutory,
                final_price,
                "GAP_OPEN_FILL" if is_gap_order else "NEXT_COMPLETE_BAR",
                str(bar["bar_id"]),
            ),
        )

        total_cash_effect = raw_notional + spread + impact + statutory
        if order["side"] == "BUY":
            remaining_cash = cash - total_cash_effect
            connection.execute(
                """INSERT INTO position_lot(
                  position_lot_id,isin,symbol,strategy_id,event_id,opened_by_fill_id,opened_at_utc,
                  quantity_open,average_cost,stop_price,status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    order["isin"],
                    order["symbol"],
                    order["strategy_id"],
                    order["event_id"],
                    fill_id,
                    bar["close_time_utc"],
                    quantity,
                    final_price,
                    final_price * (1 - config.stop_loss_pct / 100),
                    "OPEN",
                ),
            )
            _record_cash(
                connection, order["strategy_id"], fill_id, -total_cash_effect, remaining_cash
            )
        else:
            proceeds = raw_notional - spread - impact - statutory
            remaining_cash = cash + proceeds
            lot = connection.execute(
                """SELECT position_lot_id,quantity_open FROM position_lot
                   WHERE strategy_id=? AND symbol=? AND status='OPEN'
                   ORDER BY opened_at_utc LIMIT 1""",
                (order["strategy_id"], order["symbol"]),
            ).fetchone()
            assert lot is not None
            left = int(lot["quantity_open"]) - quantity
            connection.execute(
                "UPDATE position_lot SET quantity_open=?,status=? WHERE position_lot_id=?",
                (left, "CLOSED" if left == 0 else "OPEN", lot["position_lot_id"]),
            )
            _record_cash(connection, order["strategy_id"], fill_id, proceeds, remaining_cash)

        # Update remaining order quantity atomically (§32.5)
        new_remaining = remaining_qty - quantity
        if new_remaining == 0:
            new_order_status = "FILLED"
            stats["filled"] += 1
        else:
            new_order_status = "PARTIALLY_FILLED"
            stats["partially_filled"] += 1

        connection.execute(
            "UPDATE paper_order SET quantity_remaining=?, status=? WHERE paper_order_id=?",
            (new_remaining, new_order_status, order["paper_order_id"]),
        )

    return stats


def create_exit_intents(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """SELECT position_lot_id,event_id,strategy_id,symbol,isin,quantity_open
           FROM position_lot WHERE status='OPEN'"""
    ).fetchall()
    count = 0
    now = datetime.now(UTC)
    for lot in rows:
        latest_bar = connection.execute(
            """SELECT low FROM price_bar WHERE symbol=? AND is_complete=1
               ORDER BY close_time_utc DESC LIMIT 1""",
            (lot["symbol"],),
        ).fetchone()
        stop = connection.execute(
            "SELECT stop_price FROM position_lot WHERE position_lot_id=?", (lot["position_lot_id"],)
        ).fetchone()
        if not latest_bar or not stop or float(latest_bar["low"]) > float(stop["stop_price"]):
            continue
        exists = connection.execute(
            """SELECT 1 FROM paper_order WHERE strategy_id=? AND symbol=? AND side='SELL'
               AND status IN ('PENDING_EXIT','PENDING_PRICE','PARTIALLY_FILLED')""",
            (lot["strategy_id"], lot["symbol"]),
        ).fetchone()
        if exists:
            continue
        connection.execute(
            """INSERT INTO paper_order(
              paper_order_id,client_order_id,event_id,strategy_id,strategy_version,symbol,isin,side,
              quantity_requested,quantity_remaining,order_type,limit_price,trigger_price,
              participation_cap_pct,valid_from_utc,valid_until_utc,status,decision_snapshot_hash,created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                f"{lot['position_lot_id']}:STOP:SELL",
                lot["event_id"],
                lot["strategy_id"],
                "1",
                lot["symbol"],
                lot["isin"],
                "SELL",
                lot["quantity_open"],
                lot["quantity_open"],
                "PAPER_MARKET",
                None,
                None,
                1.0,
                now.isoformat(),
                (now + timedelta(days=1)).isoformat(),
                "PENDING_EXIT",
                lot["position_lot_id"],
                now.isoformat(),
            ),
        )
        count += 1
    return count
