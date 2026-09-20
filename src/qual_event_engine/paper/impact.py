from __future__ import annotations

import math


def calculate_market_impact_bps(
    order_shares: float,
    bar_volume_shares: float,
    daily_volatility: float = 0.02,
    participation_cap_pct: float = 10.0,
) -> float:
    """Calculates market impact in basis points.
    Uses square-root law: Impact = eta * sigma * sqrt(OrderQty / BarVolume).
    Capped at 50 bps max slippage.
    """
    if bar_volume_shares <= 0 or order_shares <= 0:
        return 5.0  # Base default 5 bps

    participation = (order_shares / bar_volume_shares) * 100.0
    # Base slippage 2.0 bps + participation penalty
    impact_bps = 2.0 + 15.0 * math.sqrt(participation / 100.0)
    return min(50.0, max(2.0, impact_bps))


def apply_slippage(price: float, side: str, impact_bps: float) -> float:
    slippage_fraction = impact_bps / 10_000.0
    if side.upper() == "BUY":
        return price * (1.0 + slippage_fraction)
    else:
        return price * (1.0 - slippage_fraction)
