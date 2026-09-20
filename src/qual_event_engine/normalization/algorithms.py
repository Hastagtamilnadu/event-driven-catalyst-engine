from __future__ import annotations

import re
from datetime import datetime, time
from typing import Literal

# ---------------------------------------------------------------------------
# §32.1 Credit-Rating Normalization Scale Mapping
# ---------------------------------------------------------------------------

RATING_SCALE: dict[str, int] = {
    "AAA": 20,
    "AA+": 19,
    "AA": 18,
    "AA-": 17,
    "A+": 16,
    "A": 15,
    "A-": 14,
    "BBB+": 13,
    "BBB": 12,
    "BBB-": 11,
    "BB+": 10,
    "BB": 9,
    "BB-": 8,
    "B+": 7,
    "B": 6,
    "B-": 5,
    "C+": 4,
    "C": 3,
    "C-": 2,
    "D": 1,
}

OUTLOOK_ADJUSTMENT: dict[str, float] = {
    "POSITIVE": 0.5,
    "STABLE": 0.0,
    "NEGATIVE": -0.5,
}


def normalize_rating(rating_str: str) -> int | None:
    """Normalizes an agency rating (e.g. 'CRISIL AA+', '[ICRA]A', 'CARE BBB-') to 1-20 scale."""
    cleaned = rating_str.strip().upper()
    # Strip agency prefixes such as CRISIL, ICRA, CARE, IND, BWR
    cleaned = re.sub(r"^\[?(?:CRISIL|ICRA|CARE|IND(?:IA)?|BWR|ACUITE)\]?\s*", "", cleaned)
    # Remove outlook words from string if embedded
    cleaned = re.sub(r"\s*\((?:STABLE|POSITIVE|NEGATIVE|WATCH.*?)\)", "", cleaned).strip()

    return RATING_SCALE.get(cleaned)


def calculate_rating_notch_change(
    previous_rating: str | None,
    new_rating: str | None,
    previous_outlook: str | None = None,
    new_outlook: str | None = None,
) -> float | None:
    """Calculates the net notch change between previous and new credit ratings."""
    if not previous_rating or not new_rating:
        return None

    prev_score = normalize_rating(previous_rating)
    new_score = normalize_rating(new_rating)
    if prev_score is None or new_score is None:
        return None

    base_change = float(new_score - prev_score)
    if previous_outlook and new_outlook:
        prev_adj = OUTLOOK_ADJUSTMENT.get(previous_outlook.upper(), 0.0)
        new_adj = OUTLOOK_ADJUSTMENT.get(new_outlook.upper(), 0.0)
        base_change += (new_adj - prev_adj)

    return base_change


# ---------------------------------------------------------------------------
# §32.2 Source Lead-Time Calculation Algorithm
# ---------------------------------------------------------------------------

TradingSessionPhase = Literal[
    "PRE_MARKET", "INTRADAY_EARLY", "INTRADAY_MID", "INTRADAY_LATE", "POST_MARKET"
]


def classify_market_phase(dt: datetime) -> TradingSessionPhase:
    """Classifies an IST timestamp into standard Indian market trading session phases."""
    t = dt.time()
    if t < time(9, 15):
        return "PRE_MARKET"
    elif t < time(11, 30):
        return "INTRADAY_EARLY"
    elif t < time(13, 30):
        return "INTRADAY_MID"
    elif t <= time(15, 30):
        return "INTRADAY_LATE"
    else:
        return "POST_MARKET"


def calculate_lead_time_seconds(dissemination_time: datetime, trade_time: datetime) -> float:
    """Computes source lead time in seconds: Delta t = t_trade - t_dissemination."""
    delta = trade_time - dissemination_time
    return max(0.0, delta.total_seconds())


# ---------------------------------------------------------------------------
# §32.3 Size-to-Order-Book Ratio Calculation Formula
# ---------------------------------------------------------------------------

def calculate_materiality_ratio(
    order_value_inr: float,
    order_book_inr: float | None = None,
    ttm_revenue_inr: float | None = None,
) -> tuple[float, str]:
    """Calculates order materiality ratio against order book or TTM revenue fallback.
    
    Returns (ratio, denominator_type).
    """
    if order_book_inr is not None and order_book_inr > 0:
        return (order_value_inr / order_book_inr, "ORDER_BOOK")
    elif ttm_revenue_inr is not None and ttm_revenue_inr > 0:
        return (order_value_inr / ttm_revenue_inr, "TTM_REVENUE")
    else:
        return (0.0, "UNKNOWN")


# ---------------------------------------------------------------------------
# §32.4 Intraday Volume Activity Multiple vs ADT20 Curve Algorithm
# ---------------------------------------------------------------------------

def expected_cumulative_volume_fraction(market_time: time) -> float:
    """Computes expected cumulative fraction of daily volume at market_time for Indian equities.
    
    09:15 - 10:00: 20% (slope 0.20 / 45m = 0.00444/m)
    10:00 - 11:30: 20% (cumulative 40%, slope 0.20 / 90m = 0.00222/m)
    11:30 - 13:30: 20% (cumulative 60%, slope 0.20 / 120m = 0.00167/m)
    13:30 - 14:30: 15% (cumulative 75%, slope 0.15 / 60m = 0.00250/m)
    14:30 - 15:30: 25% (cumulative 100%, slope 0.25 / 60m = 0.00417/m)
    """
    market_open = time(9, 15)
    market_close = time(15, 30)

    if market_time <= market_open:
        return 0.01  # Minimum baseline at open
    if market_time >= market_close:
        return 1.0

    minutes_from_open = (
        (market_time.hour - 9) * 60 + market_time.minute - 15
    )

    if minutes_from_open <= 45:  # up to 10:00
        return 0.20 * (minutes_from_open / 45.0)
    elif minutes_from_open <= 135:  # up to 11:30
        return 0.20 + 0.20 * ((minutes_from_open - 45) / 90.0)
    elif minutes_from_open <= 255:  # up to 13:30
        return 0.40 + 0.20 * ((minutes_from_open - 135) / 120.0)
    elif minutes_from_open <= 315:  # up to 14:30
        return 0.60 + 0.15 * ((minutes_from_open - 255) / 60.0)
    else:  # up to 15:30
        return 0.75 + 0.25 * ((minutes_from_open - 315) / 60.0)


def calculate_volume_activity_multiple(
    cumulative_volume_shares: float,
    adv20_shares: float,
    current_market_time: time,
) -> float:
    """Calculates activity multiple M_t = V_t / (adv20 * expected_fraction(t))."""
    if adv20_shares <= 0:
        return 1.0

    expected_frac = expected_cumulative_volume_fraction(current_market_time)
    expected_vol = adv20_shares * expected_frac
    if expected_vol <= 0:
        return 1.0

    return cumulative_volume_shares / expected_vol
