from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, slots=True)
class PITFundamentals:
    isin: str
    symbol: str
    period_end_date: str
    dissemination_time_utc: datetime
    system_first_seen_at_utc: datetime
    eligibility_timestamp_utc: datetime
    ttm_revenue_inr: float
    ebitda_inr: float
    net_profit_inr: float
    net_debt_inr: float


class FundamentalsManager:
    """Manages point-in-time corporate fundamentals with zero lookahead bias."""

    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = data_root or Path("D:/02_Trading/data")
        self._df: pd.DataFrame | None = None

    def get_pit_path(self) -> Path:
        return self.data_root / "master_point_in_time_fundamentals.parquet"

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            p = self.get_pit_path()
            if p.exists():
                self._df = pd.read_parquet(p)
            else:
                self._df = pd.DataFrame()
        return self._df

    def get_pit_fundamentals(
        self,
        symbol: str,
        as_of_utc: datetime,
    ) -> PITFundamentals | None:
        df = self._load()
        if df.empty:
            return None

        as_of_str = as_of_utc.isoformat()
        sym_upper = symbol.upper()
        
        # Check symbol column
        if "symbol" not in df.columns:
            return None

        filtered = df[df["symbol"].str.upper() == sym_upper]
        if "eligibility_timestamp_utc" in filtered.columns:
            filtered = filtered[filtered["eligibility_timestamp_utc"] <= as_of_str]
            filtered = filtered.sort_values("eligibility_timestamp_utc", ascending=False)
        elif "eligible_at_utc" in filtered.columns:
            filtered = filtered[filtered["eligible_at_utc"] <= as_of_str]
            filtered = filtered.sort_values("eligible_at_utc", ascending=False)

        if filtered.empty:
            return None

        row = filtered.iloc[0]
        return PITFundamentals(
            isin=str(row.get("isin", "")),
            symbol=str(row.get("symbol", symbol)),
            period_end_date=str(row.get("period_end_date", row.get("period_end", ""))),
            dissemination_time_utc=row.get("dissemination_time_utc", as_of_utc),
            system_first_seen_at_utc=row.get("system_first_seen_at_utc", as_of_utc),
            eligibility_timestamp_utc=row.get("eligibility_timestamp_utc", as_of_utc),
            ttm_revenue_inr=float(row.get("ttm_revenue_inr", row.get("value", 0.0))),
            ebitda_inr=float(row.get("ebitda_inr", 0.0)),
            net_profit_inr=float(row.get("net_profit_inr", 0.0)),
            net_debt_inr=float(row.get("net_debt_inr", 0.0)),
        )
