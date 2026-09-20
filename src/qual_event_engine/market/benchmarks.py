from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, slots=True)
class BenchmarkReturn:
    benchmark_symbol: str
    date: str
    close: float
    daily_return_pct: float


class BenchmarkManager:
    """Provides market benchmarks (e.g. NIFTY50, NIFTY500) and beta / excess return calculations."""

    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = data_root or Path("D:/02_Trading/data")
        self._benchmark_cache: dict[str, pd.DataFrame] = {}

    def get_benchmark_bars(self, benchmark_symbol: str = "NIFTY50") -> pd.DataFrame:
        if benchmark_symbol in self._benchmark_cache:
            return self._benchmark_cache[benchmark_symbol]

        p = self.data_root / "master_market_bars.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if "symbol" in df.columns:
                bm_df = df[df["symbol"].str.upper() == benchmark_symbol.upper()]
                self._benchmark_cache[benchmark_symbol] = bm_df
                return bm_df
        return pd.DataFrame()

    def calculate_excess_return(
        self,
        stock_return: float,
        benchmark_symbol: str,
        date_str: str,
    ) -> float:
        bm_bars = self.get_benchmark_bars(benchmark_symbol)
        if bm_bars.empty:
            return stock_return

        time_col = "close_time_utc" if "close_time_utc" in bm_bars.columns else ("date" if "date" in bm_bars.columns else None)
        if not time_col:
            return stock_return

        match = bm_bars[bm_bars[time_col].astype(str).str.startswith(date_str)]
        if match.empty:
            return stock_return

        open_col = "open" if "open" in match.columns else "open_price"
        close_col = "close" if "close" in match.columns else "close_price"

        if open_col in match.columns and close_col in match.columns:
            open_p = float(match[open_col].iloc[0])
            close_p = float(match[close_col].iloc[-1])
            bm_ret = (close_p - open_p) / open_p if open_p > 0 else 0.0
            return stock_return - bm_ret
        return stock_return
