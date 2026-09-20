from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CompanyDossier:
    symbol: str
    legal_name: str
    sector: str | None
    market_cap_inr: float | None
    ttm_revenue_inr: float | None
    ebitda_inr: float | None
    net_profit_inr: float | None
    net_debt_inr: float | None
    surveillance_status: str
    price_band_pct: float | None
    prior_events: list[dict[str, Any]]
    as_of_utc: datetime


class DossierBuilder:
    """Builds a point-in-time contextual dossier for a company prior to analyst assessment."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def build_dossier(self, symbol: str, as_of_utc: datetime) -> CompanyDossier:
        as_of_str = as_of_utc.isoformat()

        # Fetch membership & metadata
        cur = self.connection.execute(
            """
            SELECT legal_name, series, listed_status, surveillance_status,
                   price_band_pct, market_cap_inr
            FROM security_membership
            WHERE symbol = ? AND effective_from_utc <= ?
            ORDER BY effective_from_utc DESC
            LIMIT 1
            """,
            (symbol.upper(), as_of_str),
        )
        mem = cur.fetchone()
        legal_name = mem[0] if mem else symbol
        surv = mem[3] if mem else "NONE"
        pb = mem[4] if mem else None
        mcap = mem[5] if mem else None

        # Fetch latest point-in-time fundamentals
        def get_fund(metric: str) -> float | None:
            c = self.connection.execute(
                """
                SELECT value FROM fundamental_metrics
                WHERE symbol = ? AND metric = ? AND eligible_at_utc <= ?
                ORDER BY eligible_at_utc DESC
                LIMIT 1
                """,
                (symbol.upper(), metric, as_of_str),
            )
            r = c.fetchone()
            return float(r[0]) if r else None

        ttm_rev = get_fund("TTM_REVENUE_INR")
        ebitda = get_fund("EBITDA_INR")
        net_profit = get_fund("NET_PROFIT_INR")
        net_debt = get_fund("NET_DEBT_INR")

        # Fetch recent historical events for this symbol
        c_ev = self.connection.execute(
            """
            SELECT event_id, event_type, firmness_level, event_occurred_at_utc, headline
            FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ?
            ORDER BY event_occurred_at_utc DESC
            LIMIT 5
            """,
            (symbol.upper(), as_of_str),
        )
        prior_events = [
            {
                "event_id": str(r[0]),
                "event_type": r[1],
                "firmness_level": r[2],
                "occurred_at": r[3],
                "headline": r[4],
            }
            for r in c_ev.fetchall()
        ]

        return CompanyDossier(
            symbol=symbol.upper(),
            legal_name=legal_name,
            sector=None,
            market_cap_inr=mcap,
            ttm_revenue_inr=ttm_rev,
            ebitda_inr=ebitda,
            net_profit_inr=net_profit,
            net_debt_inr=net_debt,
            surveillance_status=surv,
            price_band_pct=pb,
            prior_events=prior_events,
            as_of_utc=as_of_utc,
        )
