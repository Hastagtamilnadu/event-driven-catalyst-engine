from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

ELIGIBLE_SERIES = frozenset({"EQ", "BE"})
INELIGIBLE_SURVEILLANCE = frozenset({"ASM", "GSM", "ESM", "T2T", "STAGE1", "STAGE2", "STAGE3"})
MIN_PRICE_BAND_PCT = 5.0
MIN_ADT20_INR = 20_000_000.0


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
                    eligibility_reasons=_parse_eligibility_reasons(r[9]),
                )
            )
        return result

    def is_security_eligible(self, symbol_or_isin: str, as_of_utc: datetime) -> tuple[bool, str]:
        query = """
            SELECT eligible, surveillance_status, price_band_pct, adt20_inr, series
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
        eligible, surv, pb, adt, series = row
        if not eligible:
            return False, "INELIGIBLE_MEMBERSHIP (surv=" + str(surv) + ", pb=" + str(pb) + ", adt=" + str(adt) + ")"
        if series and str(series).upper() not in ELIGIBLE_SERIES:
            return False, "SERIES_INELIGIBLE_" + str(series)
        surv_u = str(surv or "").upper()
        if surv_u in INELIGIBLE_SURVEILLANCE or (surv_u and surv_u not in {"NONE", "NORMAL"}):
            return False, "SURVEILLANCE_FLAG_" + str(surv)
        if pb is not None and float(pb) < MIN_PRICE_BAND_PCT:
            return False, "TIGHT_PRICE_BAND_" + str(pb) + "pct"
        if adt is not None and float(adt) < MIN_ADT20_INR:
            return False, "LIQUIDITY_ADT20_BELOW_THRESHOLD"
        return True, "ELIGIBLE"


def _parse_eligibility_reasons(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except json.JSONDecodeError:
        return [raw]
    return []
