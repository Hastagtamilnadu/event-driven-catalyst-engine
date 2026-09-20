from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, slots=True)
class PriceBar:
    isin: str
    symbol: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume_shares: float
    turnover_inr: float
    vwap: float


class PriceManager:
    """Provides market price lookups, OHLCV bars, and VWAP calculations."""

    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = data_root or Path("D:/02_Trading/data")
        self._bars_cache: dict[str, pd.DataFrame] = {}

    def get_market_bars_path(self) -> Path:
        return self.data_root / "master_market_bars.parquet"

    def load_bars(self, symbol: str) -> pd.DataFrame:
        if symbol in self._bars_cache:
            return self._bars_cache[symbol]

        p = self.get_market_bars_path()
        if p.exists():
            df = pd.read_parquet(p)
            if "symbol" in df.columns:
                sym_df = df[df["symbol"].str.upper() == symbol.upper()]
                self._bars_cache[symbol] = sym_df
                return sym_df
        return pd.DataFrame()

    def get_latest_price(self, symbol: str, as_of_utc: datetime | None = None) -> float | None:
        bars = self.load_bars(symbol)
        if bars.empty:
            return None
        close_col = "close" if "close" in bars.columns else ("close_price" if "close_price" in bars.columns else None)
        if not close_col:
            return None

        time_col = "close_time_utc" if "close_time_utc" in bars.columns else ("date" if "date" in bars.columns else None)
        if as_of_utc and time_col:
            as_of_str = as_of_utc.isoformat()
            filtered = bars[bars[time_col] <= as_of_str]
            if filtered.empty:
                return None
            return float(filtered[close_col].iloc[-1])
        return float(bars[close_col].iloc[-1])

    def get_vwap(self, symbol: str, date_str: str) -> float | None:
        bars = self.load_bars(symbol)
        if bars.empty:
            return None
        time_col = "close_time_utc" if "close_time_utc" in bars.columns else ("date" if "date" in bars.columns else None)
        if not time_col:
            return None
        daily = bars[bars[time_col].astype(str).str.startswith(date_str)]
        if daily.empty:
            return None

        turnover_col = "turnover_inr" if "turnover_inr" in daily.columns else "turnover"
        vol_col = "volume_shares" if "volume_shares" in daily.columns else "volume"
        close_col = "close" if "close" in daily.columns else "close_price"

        if turnover_col in daily.columns and vol_col in daily.columns:
            tot_to = float(daily[turnover_col].sum())
            tot_vol = float(daily[vol_col].sum())
            if tot_vol > 0:
                return tot_to / tot_vol
        if close_col in daily.columns:
            return float(daily[close_col].mean())
        return None
