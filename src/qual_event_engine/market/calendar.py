from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)

# NSE Standard Holidays (sample representative set for 2023-2026)
NSE_HOLIDAYS = {
    date(2023, 1, 26), date(2023, 3, 7), date(2023, 3, 30), date(2023, 4, 4),
    date(2023, 4, 7), date(2023, 4, 14), date(2023, 5, 1), date(2023, 6, 28),
    date(2023, 8, 15), date(2023, 9, 19), date(2023, 10, 2), date(2023, 10, 24),
    date(2023, 11, 14), date(2023, 11, 27), date(2023, 12, 25),
    date(2024, 1, 26), date(2024, 3, 8), date(2024, 3, 25), date(2024, 3, 29),
    date(2024, 4, 11), date(2024, 4, 17), date(2024, 5, 1), date(2024, 5, 20),
    date(2024, 6, 17), date(2024, 7, 17), date(2024, 8, 15), date(2024, 10, 2),
    date(2024, 11, 1), date(2024, 11, 15), date(2024, 12, 25),
    date(2025, 1, 26), date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31),
    date(2025, 4, 10), date(2025, 4, 14), date(2025, 4, 18), date(2025, 5, 1),
    date(2025, 8, 15), date(2025, 8, 27), date(2025, 10, 2), date(2025, 10, 21),
    date(2025, 11, 5), date(2025, 12, 25),
    date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 20), date(2026, 4, 3),
    date(2026, 4, 14), date(2026, 5, 1), date(2026, 8, 15), date(2026, 10, 2),
    date(2026, 11, 10), date(2026, 12, 25),
}


class TradingCalendar:
    """NSE Trading Calendar with market hours, holiday tracking, and session transitions."""

    @staticmethod
    def is_trading_day(d: date) -> bool:
        if d.weekday() >= 5:  # Saturday or Sunday
            return False
        return d not in NSE_HOLIDAYS

    @classmethod
    def next_trading_day(cls, current: date) -> date:
        cand = current + timedelta(days=1)
        while not cls.is_trading_day(cand):
            cand += timedelta(days=1)
        return cand

    @classmethod
    def prev_trading_day(cls, current: date) -> date:
        cand = current - timedelta(days=1)
        while not cls.is_trading_day(cand):
            cand -= timedelta(days=1)
        return cand

    @classmethod
    def is_market_open(cls, dt_utc: datetime) -> bool:
        dt_ist = dt_utc.astimezone(IST)
        if not cls.is_trading_day(dt_ist.date()):
            return False
        return MARKET_OPEN_TIME <= dt_ist.time() <= MARKET_CLOSE_TIME

    @classmethod
    def get_session_roll_time(cls, d: date) -> datetime:
        """Returns 15:30 IST in UTC for a given trading date."""
        ist_dt = datetime.combine(d, MARKET_CLOSE_TIME, tzinfo=IST)
        return ist_dt.astimezone(UTC)
