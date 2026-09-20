from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UniverseMember:
    isin: str
    symbol: str
    legal_name: str
    series: str
    listed_status: str
    surveillance_status: str
    price_band_pct: float | None
    adt20_inr: float | None
    eligible: bool
    eligibility_reasons: list[str]


class SecurityUniverse:
    """Manages point-in-time security universe, liquidity screens, and surveillance filters."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_eligible_universe(self, as_of_utc: datetime) -> list[UniverseMember]:
        query = """
            SELECT isin, symbol, legal_name, series, listed_status, surveillance_status,
                   price_band_pct, adt20_inr, eligible, eligibility_reasons
            FROM security_membership
            WHERE effective_from_utc <= ?
              AND (effective_to_utc IS NULL OR effective_to_utc > ?)
              AND eligible = 1
        """
        cursor = self.connection.execute(query, (as_of_utc.isoformat(), as_of_utc.isoformat()))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append(
                UniverseMember(
                    isin=r[0] or "",
                    symbol=r[1],
                    legal_name=r[2],
                    series=r[3],
                    listed_status=r[4],
                    surveillance_status=r[5],
                    price_band_pct=r[6],
                    adt20_inr=r[7],
                    eligible=bool(r[8]),
                    eligibility_reasons=eval(r[9]) if isinstance(r[9], str) and r[9].startswith("[") else [],
                )
            )
        return result

    def is_security_eligible(self, symbol_or_isin: str, as_of_utc: datetime) -> tuple[bool, str]:
        query = """
            SELECT eligible, surveillance_status, price_band_pct, adt20_inr
            FROM security_membership
            WHERE (symbol = ? OR isin = ?)
              AND effective_from_utc <= ?
              AND (effective_to_utc IS NULL OR effective_to_utc > ?)
            ORDER BY effective_from_utc DESC
            LIMIT 1
        """
        cursor = self.connection.execute(
            query,
            (symbol_or_isin.upper(), symbol_or_isin, as_of_utc.isoformat(), as_of_utc.isoformat()),
        )
        row = cursor.fetchone()
        if not row:
            return False, "SECURITY_NOT_FOUND_IN_UNIVERSE"
        eligible, surv, pb, adt = row
        if not eligible:
            return False, f"INELIGIBLE_MEMBERSHIP (surv={surv}, pb={pb}, adt={adt})"
        if surv and surv not in ("NONE", "NORMAL", ""):
            return False, f"SURVEILLANCE_FLAG_{surv}"
        if pb is not None and pb < 5.0:
            return False, f"TIGHT_PRICE_BAND_{pb}%"
        return True, "ELIGIBLE"
