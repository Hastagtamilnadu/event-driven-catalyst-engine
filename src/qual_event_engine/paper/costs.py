from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndianEquityCosts:
    stt_inr: float
    exchange_charges_inr: float
    sebi_charges_inr: float
    stamp_duty_inr: float
    brokerage_inr: float
    gst_inr: float
    total_statutory_costs_inr: float


def calculate_equity_costs(
    notional: float,
    side: str = "BUY",
    brokerage_rate_pct: float = 0.0,
) -> IndianEquityCosts:
    """Computes Indian delivery equity transaction costs per Section 23:
    - STT: 0.10% on both BUY and SELL for delivery
    - Exchange turnover: 0.00325%
    - SEBI turnover: 0.00010%
    - Stamp duty: 0.015% on BUY only
    - GST: 18% on (brokerage + exchange charges + SEBI charges)
    """
    stt = notional * 0.0010
    exchange = notional * 0.0000325
    sebi = notional * 0.0000010
    stamp = notional * 0.00015 if side.upper() == "BUY" else 0.0
    brokerage = notional * (brokerage_rate_pct / 100.0)
    gst = (brokerage + exchange + sebi) * 0.18
    total = stt + exchange + sebi + stamp + brokerage + gst

    return IndianEquityCosts(
        stt_inr=round(stt, 2),
        exchange_charges_inr=round(exchange, 2),
        sebi_charges_inr=round(sebi, 2),
        stamp_duty_inr=round(stamp, 2),
        brokerage_inr=round(brokerage, 2),
        gst_inr=round(gst, 2),
        total_statutory_costs_inr=round(total, 2),
    )
