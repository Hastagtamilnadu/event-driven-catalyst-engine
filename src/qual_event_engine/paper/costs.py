from __future__ import annotations

"""§18.1 Versioned cost model.

Each cost configuration carries effective date, source, formula, and version for:
- delivery STT
- exchange and regulatory charges
- stamp duty, GST, and brokerage
- bid-ask spread
- market impact
- auction/circuit penalties

Each paper trade reports gross P&L, individual cost components, net P&L before tax, and uncertainty.
Tax is separately reported.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class CostComponentConfig:
    name: str
    effective_date: date
    source: str
    formula: str
    version: str
    rate: float


@dataclass(frozen=True, slots=True)
class IndianEquityCosts:
    stt_inr: float
    exchange_charges_inr: float
    sebi_charges_inr: float
    stamp_duty_inr: float
    brokerage_inr: float
    gst_inr: float
    spread_inr: float
    market_impact_inr: float
    auction_circuit_penalty_inr: float
    total_statutory_costs_inr: float
    config_version: str


@dataclass(frozen=True, slots=True)
class PaperTradeCostReport:
    gross_pnl_inr: float
    cost_components: dict[str, float]
    net_pnl_before_tax_inr: float
    tax_inr: float | None
    uncertainty: str
    config_version: str


DEFAULT_EFFECTIVE = date(2024, 4, 1)
DEFAULT_SOURCE = "configs/costs.yaml"
DEFAULT_VERSION = "18.1-v1"


def default_cost_book() -> dict[str, CostComponentConfig]:
    d = DEFAULT_EFFECTIVE
    src = DEFAULT_SOURCE
    v = DEFAULT_VERSION
    return {
        "delivery_stt": CostComponentConfig(
            "delivery_stt", d, src, "notional * 0.0010 (delivery buy and sell)", v, 0.0010
        ),
        "exchange_charges": CostComponentConfig(
            "exchange_charges", d, src, "notional * 0.0000325", v, 0.0000325
        ),
        "regulatory_charges": CostComponentConfig(
            "regulatory_charges", d, src, "notional * 0.0000010 SEBI turnover", v, 0.0000010
        ),
        "stamp_duty": CostComponentConfig(
            "stamp_duty", d, src, "notional * 0.00015 on BUY only", v, 0.00015
        ),
        "gst": CostComponentConfig(
            "gst", d, src, "0.18 * (brokerage + exchange + SEBI)", v, 0.18
        ),
        "brokerage": CostComponentConfig(
            "brokerage", d, src, "notional * brokerage_rate", v, 0.0
        ),
        "bid_ask_spread": CostComponentConfig(
            "bid_ask_spread", d, src, "notional * 0.0005 half-spread", v, 0.0005
        ),
        "market_impact": CostComponentConfig(
            "market_impact", d, src, "notional * (0.0005 + min(0.02, sqrt(participation)*0.01))", v, 0.0005
        ),
        "auction_circuit_penalties": CostComponentConfig(
            "auction_circuit_penalties",
            d,
            src,
            "notional * 0.0010 when auction/circuit session",
            v,
            0.0010,
        ),
    }


def calculate_equity_costs(
    notional: float,
    side: str = "BUY",
    brokerage_rate_pct: float = 0.0,
    participation_fraction: float = 0.0,
    session: str = "INTRADAY",
    book: dict[str, CostComponentConfig] | None = None,
) -> IndianEquityCosts:
    """Indian delivery equity transaction costs with versioned components."""
    cfg = book or default_cost_book()
    stt = notional * cfg["delivery_stt"].rate
    exchange = notional * cfg["exchange_charges"].rate
    sebi = notional * cfg["regulatory_charges"].rate
    stamp = notional * cfg["stamp_duty"].rate if side.upper() == "BUY" else 0.0
    brokerage = notional * (brokerage_rate_pct / 100.0)
    gst = (brokerage + exchange + sebi) * cfg["gst"].rate
    spread = notional * cfg["bid_ask_spread"].rate
    impact = notional * (
        cfg["market_impact"].rate + min(0.02, (max(participation_fraction, 0.0) ** 0.5) * 0.01)
    )
    penalty = 0.0
    if session.upper() in {"PRE_OPEN", "AUCTION", "CIRCUIT"}:
        penalty = notional * cfg["auction_circuit_penalties"].rate
    statutory = stt + exchange + sebi + stamp + brokerage + gst
    return IndianEquityCosts(
        stt_inr=round(stt, 2),
        exchange_charges_inr=round(exchange, 2),
        sebi_charges_inr=round(sebi, 2),
        stamp_duty_inr=round(stamp, 2),
        brokerage_inr=round(brokerage, 2),
        gst_inr=round(gst, 2),
        spread_inr=round(spread, 2),
        market_impact_inr=round(impact, 2),
        auction_circuit_penalty_inr=round(penalty, 2),
        total_statutory_costs_inr=round(statutory, 2),
        config_version=DEFAULT_VERSION,
    )


def report_paper_trade(
    entry_notional: float,
    exit_notional: float,
    side: str = "BUY",
    participation_fraction: float = 0.0,
    session: str = "INTRADAY",
) -> PaperTradeCostReport:
    entry = calculate_equity_costs(entry_notional, side=side, participation_fraction=participation_fraction, session=session)
    exit_side = "SELL" if side.upper() == "BUY" else "BUY"
    exit_costs = calculate_equity_costs(
        exit_notional, side=exit_side, participation_fraction=participation_fraction, session=session
    )
    gross = exit_notional - entry_notional if side.upper() == "BUY" else entry_notional - exit_notional
    components = {
        "delivery_stt": entry.stt_inr + exit_costs.stt_inr,
        "exchange_charges": entry.exchange_charges_inr + exit_costs.exchange_charges_inr,
        "regulatory_charges": entry.sebi_charges_inr + exit_costs.sebi_charges_inr,
        "stamp_duty": entry.stamp_duty_inr + exit_costs.stamp_duty_inr,
        "gst": entry.gst_inr + exit_costs.gst_inr,
        "brokerage": entry.brokerage_inr + exit_costs.brokerage_inr,
        "bid_ask_spread": entry.spread_inr + exit_costs.spread_inr,
        "market_impact": entry.market_impact_inr + exit_costs.market_impact_inr,
        "auction_circuit_penalties": (
            entry.auction_circuit_penalty_inr + exit_costs.auction_circuit_penalty_inr
        ),
    }
    total_cost = sum(components.values())
    net = gross - total_cost
    uncertainty = "HIGH" if participation_fraction > 0.05 or session.upper() in {"AUCTION", "CIRCUIT"} else "MODERATE"
    return PaperTradeCostReport(
        gross_pnl_inr=round(gross, 2),
        cost_components={k: round(v, 2) for k, v in components.items()},
        net_pnl_before_tax_inr=round(net, 2),
        tax_inr=None,
        uncertainty=uncertainty,
        config_version=DEFAULT_VERSION,
    )


def cost_book_as_dicts() -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "effective_date": c.effective_date.isoformat(),
            "source": c.source,
            "formula": c.formula,
            "version": c.version,
            "rate": c.rate,
        }
        for c in default_cost_book().values()
    ]
