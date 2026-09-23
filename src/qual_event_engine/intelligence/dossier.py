from __future__ import annotations

"""§10 Company dossier and credibility flags.

Every flag has a formula_version, source_document, date, and expiry/review rule.
The dossier must say "conversion unknown" when revenue cannot be attributed
to a historical order.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from qual_event_engine.domain.enums import CredibilityFlag, EventType, FirmnessLevel

CONVERSION_UNKNOWN = "conversion unknown"

FLAG_DEFAULT_ACTIONS: dict[CredibilityFlag, str] = {
    CredibilityFlag.PLEDGE_RISK: "Review",
    CredibilityFlag.CASH_CONVERSION_RISK: "Review",
    CredibilityFlag.RECEIVABLE_RISK: "Review",
    CredibilityFlag.AUDITOR_EVENT: "Block or review by event policy",
    CredibilityFlag.RELATED_PARTY_RISK: "Review",
    CredibilityFlag.DILUTION_RISK: "Review",
    CredibilityFlag.DELIVERY_RISK: "Review",
    CredibilityFlag.DEBT_REFINANCING_RISK: "Review / Pass",
    CredibilityFlag.VALUATION_STRETCH_RISK: "Review (Requires 50%+ materiality hurdle)",
    CredibilityFlag.WORKING_CAPITAL_DRAG: "Review",
    CredibilityFlag.DELEVERAGING_DISTRESS: "Review / Block",
}

PLEDGE_POLICY_PCT = 50.0
PLEDGE_MATERIAL_RISE_PP = 10.0
CFO_PAT_DIVERGENCE_YEARS = 2
RECEIVABLE_DAYS_ELEVATED = 120.0
DILUTION_REPEAT_COUNT = 2
VALUATION_STRETCH_PREMIUM_RATIO = 2.5
WORKING_CAPITAL_MAX_DAYS = 180.0
NET_DEBT_EBITDA_MAX_RATIO = 4.0
INTEREST_COVERAGE_MIN_RATIO = 1.5
DEBT_REFINANCING_ROLLOVER_RATIO = 0.60
FORMULA_VERSION = "10.1-v2"


@dataclass(frozen=True, slots=True)
class ValuationProfile:
    trailing_pe: float | None = None
    sector_median_pe: float | None = None
    pb_ratio: float | None = None
    ev_ebitda: float | None = None
    net_debt_to_ebitda: float | None = None
    interest_coverage: float | None = None
    cash_conversion_cycle_days: float | None = None
    debt_refinancing_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class CredibilityFlagRecord:
    flag: CredibilityFlag
    triggered: bool
    formula_version: str
    source_document: str | None
    date: str | None
    expiry_or_review_rule: str
    default_action: str
    objective_condition: str


@dataclass(frozen=True, slots=True)
class QuarterlyFundamentals:
    period_end: str | None
    revenue_inr: float | None
    ebitda_margin: float | None
    pat_inr: float | None
    cfo_inr: float | None
    receivables_inr: float | None


@dataclass(frozen=True, slots=True)
class TenderOrderTimelineItem:
    event_id: str
    event_type: str
    occurred_at_utc: str | None
    headline: str | None
    firmness_level: int | None
    is_amendment: bool
    is_cancellation: bool


@dataclass(frozen=True, slots=True)
class CompanyDossier:
    # §10.2 required fields
    symbol: str
    legal_name: str
    entity_id: str | None
    isin: str | None
    sector: str | None
    market_cap_inr: float | None
    free_float: float | None
    adv20: float | None
    adt20: float | None
    price_band_pct: float | None
    surveillance_status: str
    last_four_quarters: list[QuarterlyFundamentals]
    tender_order_timeline: list[TenderOrderTimelineItem]
    linked_execution_evidence: list[dict[str, Any]]
    credibility_flags: list[CredibilityFlagRecord]
    prior_events: list[dict[str, Any]]
    paper_study_outcomes: list[dict[str, Any]]
    data_quality_warnings: list[str]
    missing_field_warnings: list[str]
    conversion_attribution: str
    as_of_utc: datetime
    # retained compatibility fields
    ttm_revenue_inr: float | None = None
    ebitda_inr: float | None = None
    net_profit_inr: float | None = None
    net_debt_inr: float | None = None
    valuation_profile: ValuationProfile | None = None


class DossierBuilder:
    """Point-in-time company dossier prior to analyst assessment (§10.2)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def build_dossier(self, symbol: str, as_of_utc: datetime) -> CompanyDossier:
        as_of_str = as_of_utc.isoformat()
        symbol_u = symbol.upper()
        warnings: list[str] = []
        missing: list[str] = []

        mem = self._membership(symbol_u, as_of_str)
        legal_name = str(mem["legal_name"]) if mem else symbol_u
        surv = str(mem["surveillance_status"]) if mem else "NONE"
        pb = float(mem["price_band_pct"]) if mem and mem["price_band_pct"] is not None else None
        mcap = float(mem["market_cap_inr"]) if mem and mem["market_cap_inr"] is not None else None
        adv20 = self._optional_float(mem, "adv20_shares") if mem else None
        adt20 = self._optional_float(mem, "adt20_inr") if mem else None
        isin = str(mem["isin"]) if mem and mem["isin"] else None
        if mem is None:
            missing.append("security_membership")
        if adv20 is None:
            missing.append("ADV20")
        if adt20 is None:
            missing.append("ADT20")
        if mcap is None:
            missing.append("market_cap_inr")
        if pb is None:
            missing.append("price_band_pct")

        entity_id, sector, free_float = self._entity_identity(symbol_u, isin)
        if entity_id is None:
            missing.append("entity identity")

        quarters = self._last_four_quarters(symbol_u, as_of_str)
        if len(quarters) < 4:
            missing.append("last four reported quarters")

        ttm_rev = self._metric(symbol_u, "TTM_REVENUE_INR", as_of_str) or self._sum_revenue(quarters)
        ebitda = self._metric(symbol_u, "EBITDA_INR", as_of_str)
        net_profit = self._metric(symbol_u, "NET_PROFIT_INR", as_of_str) or self._latest_pat(quarters)
        net_debt = self._metric(symbol_u, "NET_DEBT_INR", as_of_str)

        timeline = self._tender_order_timeline(symbol_u, as_of_str)
        execution = self._linked_execution_evidence(symbol_u, as_of_str)
        conversion = self._conversion_attribution(timeline, execution, ttm_rev, missing)

        val_profile = self._valuation_profile(symbol_u, as_of_str, ttm_rev, ebitda, net_debt, quarters)
        flags = self._evaluate_all_flags(symbol_u, as_of_str, quarters, timeline, execution, val_profile)
        prior, studies = self._prior_events_and_studies(symbol_u, as_of_str)

        if surv not in {"NONE", "NORMAL"}:
            warnings.append("surveillance status is not NORMAL")
        if pb is not None and pb <= 5.0:
            warnings.append("price band is restricted (<= 5%)")

        return CompanyDossier(
            symbol=symbol_u,
            legal_name=legal_name,
            entity_id=entity_id,
            isin=isin,
            sector=sector,
            market_cap_inr=mcap,
            free_float=free_float,
            adv20=adv20,
            adt20=adt20,
            price_band_pct=pb,
            surveillance_status=surv,
            last_four_quarters=quarters,
            tender_order_timeline=timeline,
            linked_execution_evidence=execution,
            credibility_flags=flags,
            prior_events=prior,
            paper_study_outcomes=studies,
            data_quality_warnings=warnings,
            missing_field_warnings=missing,
            conversion_attribution=conversion,
            as_of_utc=as_of_utc,
            ttm_revenue_inr=ttm_rev,
            ebitda_inr=ebitda,
            net_profit_inr=net_profit,
            net_debt_inr=net_debt,
            valuation_profile=val_profile,
        )

    def _membership(self, symbol: str, as_of_str: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self.connection.execute(
                """
                SELECT * FROM security_membership
                WHERE symbol = ? AND effective_from_utc <= ?
                  AND (effective_to_utc IS NULL OR effective_to_utc > ?)
                ORDER BY effective_from_utc DESC
                LIMIT 1
                """,
                (symbol, as_of_str, as_of_str),
            ).fetchone(),
        )

    def _entity_identity(
        self, symbol: str, isin: str | None
    ) -> tuple[str | None, str | None, float | None]:
        row = None
        if isin:
            row = self.connection.execute(
                "SELECT * FROM entity WHERE isin = ? LIMIT 1", (isin,)
            ).fetchone()
        if row is None:
            cols = {
                str(r[0])
                for r in self.connection.execute(
                    "SELECT name FROM pragma_table_info(?)", ("entity",)
                ).fetchall()
            }
            if "primary_symbol" in cols:
                row = self.connection.execute(
                    "SELECT * FROM entity WHERE primary_symbol = ? LIMIT 1", (symbol,)
                ).fetchone()
        if row is None:
            return None, None, None
        keys = set(row.keys())
        entity_id = str(row["entity_id"]) if "entity_id" in keys else None
        sector = str(row["sector"]) if "sector" in keys and row["sector"] is not None else None
        free_float = (
            float(row["free_float"]) if "free_float" in keys and row["free_float"] is not None else None
        )
        return entity_id, sector, free_float

    def _metric(self, symbol: str, metric: str, as_of_str: str) -> float | None:
        row = self.connection.execute(
            """
            SELECT value FROM point_in_time_fundamental
            WHERE symbol = ? AND metric = ? AND eligible_at_utc <= ?
            ORDER BY eligible_at_utc DESC
            LIMIT 1
            """,
            (symbol, metric, as_of_str),
        ).fetchone()
        if row:
            return float(row[0])
        tables = {
            str(r[0])
            for r in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "fundamental_metrics" not in tables:
            return None
        row = self.connection.execute(
            """
            SELECT value FROM fundamental_metrics
            WHERE symbol = ? AND metric = ? AND eligible_at_utc <= ?
            ORDER BY eligible_at_utc DESC
            LIMIT 1
            """,
            (symbol, metric, as_of_str),
        ).fetchone()
        return float(row[0]) if row else None

    def _last_four_quarters(self, symbol: str, as_of_str: str) -> list[QuarterlyFundamentals]:
        periods: list[str] = []
        for metric in ("REVENUE_INR", "TTM_REVENUE_INR", "PAT_INR", "CFO_INR", "RECEIVABLES_INR"):
            rows = self.connection.execute(
                """
                SELECT DISTINCT period_end FROM point_in_time_fundamental
                WHERE symbol = ? AND metric = ? AND eligible_at_utc <= ?
                  AND period_end IS NOT NULL
                ORDER BY period_end DESC
                """,
                (symbol, metric, as_of_str),
            ).fetchall()
            for r in rows:
                if r[0] not in periods:
                    periods.append(str(r[0]))
        periods = periods[:4]
        out: list[QuarterlyFundamentals] = []
        for period in periods:
            out.append(
                QuarterlyFundamentals(
                    period_end=period,
                    revenue_inr=self._period_metric(symbol, "REVENUE_INR", period, as_of_str),
                    ebitda_margin=self._period_metric(
                        symbol, "EBITDA_MARGIN", period, as_of_str
                    ),
                    pat_inr=self._period_metric(symbol, "PAT_INR", period, as_of_str),
                    cfo_inr=self._period_metric(symbol, "CFO_INR", period, as_of_str),
                    receivables_inr=self._period_metric(
                        symbol, "RECEIVABLES_INR", period, as_of_str
                    ),
                )
            )
        return out

    def _period_metric(
        self, symbol: str, metric: str, period_end: str, as_of_str: str
    ) -> float | None:
        row = self.connection.execute(
            """
            SELECT value FROM point_in_time_fundamental
            WHERE symbol = ? AND metric = ? AND period_end = ? AND eligible_at_utc <= ?
            ORDER BY eligible_at_utc DESC
            LIMIT 1
            """,
            (symbol, metric, period_end, as_of_str),
        ).fetchone()
        return float(row[0]) if row else None

    def _sum_revenue(self, quarters: list[QuarterlyFundamentals]) -> float | None:
        vals = [q.revenue_inr for q in quarters if q.revenue_inr is not None]
        return sum(vals) if vals else None

    def _latest_pat(self, quarters: list[QuarterlyFundamentals]) -> float | None:
        for q in quarters:
            if q.pat_inr is not None:
                return q.pat_inr
        return None

    def _tender_order_timeline(
        self, symbol: str, as_of_str: str
    ) -> list[TenderOrderTimelineItem]:
        cutoff = (datetime.fromisoformat(as_of_str) - timedelta(days=730)).isoformat()
        tender_types = (
            EventType.TENDER_L1.value,
            EventType.TENDER_AWARD.value,
            EventType.LETTER_OF_AWARD.value,
            EventType.EXECUTED_CONTRACT.value,
            EventType.TENDER_CANCELLED.value,
            EventType.ORDER_WIN.value,
            EventType.ORDER_AMENDMENT.value,
            EventType.ORDER_CANCELLATION.value,
        )
        placeholders = ",".join("?" for _ in tender_types)
        rows = self.connection.execute(
            """
            SELECT * FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ? AND event_occurred_at_utc >= ?
              AND event_type IN ("""
            + placeholders
            + """)
            ORDER BY event_occurred_at_utc DESC
            """,
            (symbol, as_of_str, cutoff, *tender_types),
        ).fetchall()
        items: list[TenderOrderTimelineItem] = []
        for r in rows:
            keys = set(r.keys())
            et = str(r["event_type"])
            firmness = int(r["firmness_level"]) if "firmness_level" in keys and r["firmness_level"] is not None else None
            items.append(
                TenderOrderTimelineItem(
                    event_id=str(r["event_id"]),
                    event_type=et,
                    occurred_at_utc=r["event_occurred_at_utc"],
                    headline=str(r["headline"]) if "headline" in keys and r["headline"] is not None else None,
                    firmness_level=firmness,
                    is_amendment=et == EventType.ORDER_AMENDMENT.value,
                    is_cancellation=et
                    in {
                        EventType.ORDER_CANCELLATION.value,
                        EventType.TENDER_CANCELLED.value,
                    },
                )
            )
        return items

    def _linked_execution_evidence(
        self, symbol: str, as_of_str: str
    ) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ?
              AND event_type = ?
            ORDER BY event_occurred_at_utc DESC
            LIMIT 20
            """,
            (symbol, as_of_str, EventType.CAPACITY_COMMISSIONED.value),
        ).fetchall()
        out = [dict(r) for r in rows]
        cols = {
            str(c[0])
            for c in self.connection.execute(
                "SELECT name FROM pragma_table_info(?)", ("canonical_event",)
            ).fetchall()
        }
        if "firmness_level" in cols:
            extra = self.connection.execute(
                """
                SELECT * FROM canonical_event
                WHERE symbol = ? AND event_occurred_at_utc <= ? AND firmness_level = ?
                ORDER BY event_occurred_at_utc DESC
                LIMIT 20
                """,
                (symbol, as_of_str, int(FirmnessLevel.EXECUTION_EVIDENCE)),
            ).fetchall()
            seen = {item["event_id"] for item in out}
            for r in extra:
                if r["event_id"] not in seen:
                    out.append(dict(r))
        return out

    def _conversion_attribution(
        self,
        timeline: list[TenderOrderTimelineItem],
        execution: list[dict[str, Any]],
        ttm_rev: float | None,
        missing: list[str],
    ) -> str:
        binding = [
            t
            for t in timeline
            if t.firmness_level is not None
            and t.firmness_level >= int(FirmnessLevel.BINDING_CONTRACT)
            and not t.is_cancellation
        ]
        if binding and not execution:
            missing.append("order-to-revenue conversion evidence")
            return CONVERSION_UNKNOWN
        if ttm_rev is None:
            return CONVERSION_UNKNOWN
        if binding and execution:
            return "conversion evidenced by linked execution records"
        return CONVERSION_UNKNOWN

    def _prior_events_and_studies(
        self, symbol: str, as_of_str: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = self.connection.execute(
            """
            SELECT * FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ?
            ORDER BY event_occurred_at_utc DESC
            LIMIT 20
            """,
            (symbol, as_of_str),
        ).fetchall()
        prior = [dict(r) for r in rows]
        studies: list[dict[str, Any]] = []
        tables = {
            str(r[0])
            for r in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "paper_order" in tables:
            study_rows = self.connection.execute(
                """
                SELECT o.paper_order_id, o.strategy_id, o.status, o.event_id
                FROM paper_order o
                JOIN canonical_event e ON e.event_id = o.event_id
                WHERE e.symbol = ? AND o.created_at_utc <= ?
                ORDER BY o.created_at_utc DESC
                LIMIT 20
                """,
                (symbol, as_of_str),
            ).fetchall()
            studies = [dict(r) for r in study_rows]
        return prior, studies

    def _evaluate_all_flags(
        self,
        symbol: str,
        as_of_str: str,
        quarters: list[QuarterlyFundamentals],
        timeline: list[TenderOrderTimelineItem],
        execution: list[dict[str, Any]],
        val_profile: ValuationProfile | None = None,
    ) -> list[CredibilityFlagRecord]:
        return [
            self._flag_pledge(symbol, as_of_str),
            self._flag_cash_conversion(quarters, as_of_str),
            self._flag_receivable(quarters, as_of_str),
            self._flag_auditor(symbol, as_of_str),
            self._flag_related_party(symbol, as_of_str),
            self._flag_dilution(symbol, as_of_str),
            self._flag_delivery(timeline, execution, as_of_str),
            self._flag_debt_refinancing(symbol, as_of_str, val_profile),
            self._flag_valuation_stretch(symbol, as_of_str, val_profile),
            self._flag_working_capital(symbol, as_of_str, quarters, val_profile),
            self._flag_deleveraging_distress(symbol, as_of_str, val_profile),
        ]

    def _valuation_profile(
        self,
        symbol: str,
        as_of_str: str,
        ttm_rev: float | None,
        ebitda: float | None,
        net_debt: float | None,
        quarters: list[QuarterlyFundamentals],
    ) -> ValuationProfile:
        pe = self._metric(symbol, "PE_RATIO", as_of_str)
        sec_pe = self._metric(symbol, "SECTOR_PE", as_of_str)
        pb = self._metric(symbol, "PB_RATIO", as_of_str)
        ev_ebitda = self._metric(symbol, "EV_EBITDA", as_of_str)
        icr = self._metric(symbol, "INTEREST_COVERAGE", as_of_str)
        ccc = self._metric(symbol, "CCC_DAYS", as_of_str)
        refinance_ratio = self._metric(symbol, "DEBT_REFINANCING_RATIO", as_of_str)

        nd_ebitda = None
        if net_debt is not None and ebitda is not None and ebitda > 0:
            nd_ebitda = net_debt / ebitda

        if ccc is None and quarters:
            days_rec = [
                q.receivables_inr / (q.revenue_inr / 90.0)
                for q in quarters
                if q.receivables_inr and q.revenue_inr and q.revenue_inr > 0
            ]
            if days_rec:
                ccc = days_rec[0] + 60.0 - 45.0

        return ValuationProfile(
            trailing_pe=pe,
            sector_median_pe=sec_pe,
            pb_ratio=pb,
            ev_ebitda=ev_ebitda,
            net_debt_to_ebitda=nd_ebitda,
            interest_coverage=icr,
            cash_conversion_cycle_days=ccc,
            debt_refinancing_ratio=refinance_ratio,
        )

    def _flag_debt_refinancing(
        self, symbol: str, as_of_str: str, val_profile: ValuationProfile | None
    ) -> CredibilityFlagRecord:
        triggered = False
        if val_profile and val_profile.debt_refinancing_ratio is not None:
            triggered = val_profile.debt_refinancing_ratio >= DEBT_REFINANCING_ROLLOVER_RATIO
        return CredibilityFlagRecord(
            flag=CredibilityFlag.DEBT_REFINANCING_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:CFF_INR",
            date=as_of_str,
            expiry_or_review_rule="Review at next financing disclosure or 90 calendar days",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.DEBT_REFINANCING_RISK],
            objective_condition="New debt fundraise accompanied by substantial debt repayment or refinancing",
        )

    def _flag_valuation_stretch(
        self, symbol: str, as_of_str: str, val_profile: ValuationProfile | None
    ) -> CredibilityFlagRecord:
        triggered = False
        if val_profile:
            pe = val_profile.trailing_pe
            sec_pe = val_profile.sector_median_pe
            if pe is not None and sec_pe is not None and sec_pe > 0:
                triggered = (pe / sec_pe) >= VALUATION_STRETCH_PREMIUM_RATIO
            elif pe is not None and pe > 60.0:
                triggered = True
        return CredibilityFlagRecord(
            flag=CredibilityFlag.VALUATION_STRETCH_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:PE_RATIO",
            date=as_of_str,
            expiry_or_review_rule="Review at price or earnings update",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.VALUATION_STRETCH_RISK],
            objective_condition="Trailing P/E exceeds 2.5x sector median or sits in top historical decile",
        )

    def _flag_working_capital(
        self,
        symbol: str,
        as_of_str: str,
        quarters: list[QuarterlyFundamentals],
        val_profile: ValuationProfile | None,
    ) -> CredibilityFlagRecord:
        triggered = False
        if val_profile and val_profile.cash_conversion_cycle_days is not None:
            triggered = val_profile.cash_conversion_cycle_days > WORKING_CAPITAL_MAX_DAYS
        return CredibilityFlagRecord(
            flag=CredibilityFlag.WORKING_CAPITAL_DRAG,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:CCC_DAYS",
            date=as_of_str,
            expiry_or_review_rule="Review at next quarterly result",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.WORKING_CAPITAL_DRAG],
            objective_condition="Cash Conversion Cycle exceeds 180 days or deteriorates materially",
        )

    def _flag_deleveraging_distress(
        self, symbol: str, as_of_str: str, val_profile: ValuationProfile | None
    ) -> CredibilityFlagRecord:
        triggered = False
        if val_profile:
            nd_ebitda = val_profile.net_debt_to_ebitda
            icr = val_profile.interest_coverage
            if nd_ebitda is not None and nd_ebitda > NET_DEBT_EBITDA_MAX_RATIO:
                triggered = True
            if icr is not None and icr < INTEREST_COVERAGE_MIN_RATIO:
                triggered = True
        return CredibilityFlagRecord(
            flag=CredibilityFlag.DELEVERAGING_DISTRESS,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:NET_DEBT_EBITDA",
            date=as_of_str,
            expiry_or_review_rule="Review at next quarterly result",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.DELEVERAGING_DISTRESS],
            objective_condition="Net Debt / EBITDA exceeds 4.0x or Interest Coverage is below 1.5x",
        )

    def _flag_pledge(self, symbol: str, as_of_str: str) -> CredibilityFlagRecord:
        current = self._metric(symbol, "PROMOTER_PLEDGE_PCT", as_of_str)
        prior = self._metric(symbol, "PROMOTER_PLEDGE_PCT_PRIOR", as_of_str)
        triggered = False
        if current is not None and current > PLEDGE_POLICY_PCT:
            triggered = True
        if current is not None and prior is not None and (current - prior) >= PLEDGE_MATERIAL_RISE_PP:
            triggered = True
        return CredibilityFlagRecord(
            flag=CredibilityFlag.PLEDGE_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:PROMOTER_PLEDGE_PCT",
            date=as_of_str,
            expiry_or_review_rule="Review at next shareholding disclosure or 90 calendar days",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.PLEDGE_RISK],
            objective_condition="Promoter pledge exceeds policy or rises materially",
        )

    def _flag_cash_conversion(
        self, quarters: list[QuarterlyFundamentals], as_of_str: str
    ) -> CredibilityFlagRecord:
        diverged = 0
        for q in quarters:
            if q.pat_inr is not None and q.cfo_inr is not None and q.pat_inr > 0 and q.cfo_inr < 0:
                diverged += 1
        triggered = diverged >= CFO_PAT_DIVERGENCE_YEARS
        return CredibilityFlagRecord(
            flag=CredibilityFlag.CASH_CONVERSION_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:CFO_INR,PAT_INR",
            date=as_of_str,
            expiry_or_review_rule="Review at next quarterly result",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.CASH_CONVERSION_RISK],
            objective_condition="Multi-year CFO/PAT divergence breaches policy",
        )

    def _flag_receivable(
        self, quarters: list[QuarterlyFundamentals], as_of_str: str
    ) -> CredibilityFlagRecord:
        days: list[float] = []
        for q in quarters:
            if q.receivables_inr is not None and q.revenue_inr and q.revenue_inr > 0:
                days.append(q.receivables_inr / (q.revenue_inr / 90.0))
        triggered = False
        if days and days[0] >= RECEIVABLE_DAYS_ELEVATED:
            triggered = True
        if len(days) >= 2 and days[0] > days[-1] * 1.25:
            triggered = True
        return CredibilityFlagRecord(
            flag=CredibilityFlag.RECEIVABLE_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="point_in_time_fundamental:RECEIVABLES_INR",
            date=as_of_str,
            expiry_or_review_rule="Review at next quarterly result",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.RECEIVABLE_RISK],
            objective_condition="Receivable days are elevated or deteriorating materially",
        )

    def _flag_auditor(self, symbol: str, as_of_str: str) -> CredibilityFlagRecord:
        auditor_types = (
            EventType.AUDITOR_RESIGNATION.value,
            EventType.REGULATORY_ADVERSE_ACTION.value,
            EventType.FORENSIC_ALLEGATION.value,
        )
        placeholders = ",".join("?" for _ in auditor_types)
        row = self.connection.execute(
            """
            SELECT * FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ?
              AND event_type IN ("""
            + placeholders
            + """)
            ORDER BY event_occurred_at_utc DESC
            LIMIT 1
            """,
            (symbol, as_of_str, *auditor_types),
        ).fetchone()
        triggered = row is not None
        return CredibilityFlagRecord(
            flag=CredibilityFlag.AUDITOR_EVENT,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document=str(row["event_id"]) if row else None,
            date=str(row["event_occurred_at_utc"]) if row else as_of_str,
            expiry_or_review_rule="Remains until successor auditor appointment evidenced",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.AUDITOR_EVENT],
            objective_condition="Resignation, qualification, or adverse filing",
        )

    def _flag_related_party(self, symbol: str, as_of_str: str) -> CredibilityFlagRecord:
        row = self.connection.execute(
            """
            SELECT event_id, event_occurred_at_utc FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ? AND event_type = ?
            ORDER BY event_occurred_at_utc DESC
            LIMIT 1
            """,
            (symbol, as_of_str, EventType.OWNERSHIP_TRANSACTION.value),
        ).fetchone()
        rel = self.connection.execute(
            """
            SELECT 1 FROM entity_relationship er
            JOIN entity e ON e.entity_id = er.parent_entity_id OR e.entity_id = er.related_entity_id
            WHERE e.isin = (SELECT isin FROM security_membership WHERE symbol = ? LIMIT 1)
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        triggered = row is not None or rel is not None
        return CredibilityFlagRecord(
            flag=CredibilityFlag.RELATED_PARTY_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document=str(row["event_id"]) if row else "entity_relationship",
            date=str(row["event_occurred_at_utc"]) if row else as_of_str,
            expiry_or_review_rule="Review at next related-party disclosure",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.RELATED_PARTY_RISK],
            objective_condition="Material related-party exposure/change",
        )

    def _flag_dilution(self, symbol: str, as_of_str: str) -> CredibilityFlagRecord:
        cutoff = (datetime.fromisoformat(as_of_str) - timedelta(days=730)).isoformat()
        count_row = self.connection.execute(
            """
            SELECT COUNT(*) FROM canonical_event
            WHERE symbol = ? AND event_occurred_at_utc <= ? AND event_occurred_at_utc >= ?
              AND event_type = ?
            """,
            (symbol, as_of_str, cutoff, EventType.OWNERSHIP_TRANSACTION.value),
        ).fetchone()
        count = int(count_row[0]) if count_row else 0
        triggered = count >= DILUTION_REPEAT_COUNT
        return CredibilityFlagRecord(
            flag=CredibilityFlag.DILUTION_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="canonical_event dilution/ownership series",
            date=as_of_str,
            expiry_or_review_rule="Review 24 months after last dilution event",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.DILUTION_RISK],
            objective_condition="Repeated equity/warrant dilution",
        )

    def _flag_delivery(
        self,
        timeline: list[TenderOrderTimelineItem],
        execution: list[dict[str, Any]],
        as_of_str: str,
    ) -> CredibilityFlagRecord:
        binding_open = [
            t
            for t in timeline
            if t.firmness_level is not None
            and t.firmness_level >= int(FirmnessLevel.BINDING_CONTRACT)
            and not t.is_cancellation
        ]
        triggered = bool(binding_open) and not execution
        return CredibilityFlagRecord(
            flag=CredibilityFlag.DELIVERY_RISK,
            triggered=triggered,
            formula_version=FORMULA_VERSION,
            source_document="canonical_event tender/order timeline",
            date=as_of_str,
            expiry_or_review_rule="Review until execution evidence is linked or order cancelled",
            default_action=FLAG_DEFAULT_ACTIONS[CredibilityFlag.DELIVERY_RISK],
            objective_condition="Prior binding order lacks expected execution evidence",
        )

    @staticmethod
    def _optional_float(row: sqlite3.Row, key: str) -> float | None:
        if key not in tuple(row.keys()) or row[key] is None:
            return None
        return float(row[key])
