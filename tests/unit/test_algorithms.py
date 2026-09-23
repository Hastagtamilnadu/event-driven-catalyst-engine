from __future__ import annotations

from datetime import UTC, datetime, time

from qual_event_engine.normalization.algorithms import (
    calculate_lead_time_seconds,
    calculate_materiality_ratio,
    calculate_rating_notch_change,
    calculate_volume_activity_multiple,
    classify_market_phase,
    expected_cumulative_volume_fraction,
    normalize_rating,
)


def test_credit_rating_normalization_and_notch_change() -> None:
    # Scale mappings
    assert normalize_rating("CRISIL AAA") == 20
    assert normalize_rating("ICRA AA+") == 19
    assert normalize_rating("CARE BBB-") == 11
    assert normalize_rating("IND D") == 1
    assert normalize_rating("UNKNOWN") is None

    # Notch change calculation
    assert calculate_rating_notch_change("A", "AA") == 3.0  # 18 - 15 = 3
    assert calculate_rating_notch_change("BBB-", "BBB") == 1.0  # 12 - 11 = 1
    assert calculate_rating_notch_change("AA+", "AAA", "POSITIVE", "STABLE") == 0.5  # (20-19) + (0 - 0.5) = 0.5
    assert calculate_rating_notch_change("AA", "AA-") == -1.0  # Downgrade


def test_lead_time_and_market_phase() -> None:
    # Market phases
    assert classify_market_phase(datetime(2026, 9, 20, 8, 30, tzinfo=UTC)) == "PRE_MARKET"
    assert classify_market_phase(datetime(2026, 9, 20, 10, 0, tzinfo=UTC)) == "INTRADAY_EARLY"
    assert classify_market_phase(datetime(2026, 9, 20, 12, 0, tzinfo=UTC)) == "INTRADAY_MID"
    assert classify_market_phase(datetime(2026, 9, 20, 14, 0, tzinfo=UTC)) == "INTRADAY_LATE"
    assert classify_market_phase(datetime(2026, 9, 20, 16, 0, tzinfo=UTC)) == "POST_MARKET"

    # Lead time
    t0 = datetime(2026, 9, 20, 9, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 20, 9, 5, 30, tzinfo=UTC)
    assert calculate_lead_time_seconds(t0, t1) == 330.0


def test_materiality_ratio() -> None:
    # Against order book
    ratio, denom = calculate_materiality_ratio(500_000_000, order_book_inr=2_000_000_000)
    assert ratio == 0.25
    assert denom == "ORDER_BOOK"

    # Fallback to TTM revenue
    ratio_fallback, denom_fallback = calculate_materiality_ratio(
        300_000_000, order_book_inr=None, ttm_revenue_inr=1_000_000_000
    )
    assert ratio_fallback == 0.30
    assert denom_fallback == "TTM_REVENUE"


def test_volume_activity_multiple() -> None:
    # At 10:00, expected fraction is 20%
    frac_10 = expected_cumulative_volume_fraction(time(10, 0))
    assert abs(frac_10 - 0.20) < 1e-4

    # At 15:30, expected fraction is 100%
    frac_close = expected_cumulative_volume_fraction(time(15, 30))
    assert frac_close == 1.0

    # Activity multiple: ADV is 100,000. At 10:00, expected is 20,000. Actual volume is 40,000 -> multiple = 2.0
    mult = calculate_volume_activity_multiple(40_000, 100_000, time(10, 0))
    assert abs(mult - 2.0) < 1e-4
