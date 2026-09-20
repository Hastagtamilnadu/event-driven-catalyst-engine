"""
Platform-wide constants (§26, §27).
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_DATA_ROOT = Path(r"D:\02_Trading\data")
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "qualitative_event_ledger.db"
DEFAULT_LOG_ROOT = DEFAULT_DATA_ROOT / "logs"
DEFAULT_ARCHIVE_ROOT = DEFAULT_DATA_ROOT / "raw_archive"

SQLITE_BUSY_TIMEOUT_MS = 5000
MAX_PARTICIPATION_PCT = 0.10  # 10% volume participation cap (§32.5)
STT_DELIVERY_PCT = 0.0010     # 0.10% STT on delivery
STAMP_DUTY_PCT = 0.00015      # 0.015% stamp duty
GST_PCT = 0.18                # 18% GST on brokerage/exchange fees
SEBI_TURNOVER_FEE_PCT = 0.000001  # INR 10 per crore

MAX_SECTOR_NAV_PCT = 0.20     # Maximum 20% NAV per sector (§16.2)
DEFAULT_BLACKLIST_SESSIONS = 20  # Default 20 trading sessions (§17)
