from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from qual_event_engine.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionStatus,
)


class ManualEvent(BaseModel):
    source_native_id: str
    source_url: HttpUrl
    source_published_at_utc: datetime
    exchange_first_seen_at_utc: datetime | None = None
    document_path: str
    event_type: str
    symbol: str = Field(min_length=1, max_length=32)
    isin: str | None = None
    legal_name: str
    headline: str
    event_status: str
    firmness_level: int = Field(ge=0, le=5)
    event_value_inr: float | None = Field(default=None, ge=0)
    ttm_revenue_inr: float | None = Field(default=None, gt=0)
    sector: str | None = None
    previous_rating: str | None = None
    new_rating: str | None = None
    counterparty: str | None = None
    entity_verified: bool = False
    evidence_pages: list[int] = Field(default_factory=list)

    def source_file(self, drop_root: Path) -> Path:
        candidate = (drop_root / self.document_path).resolve()
        if not str(candidate).startswith(str(drop_root.resolve())):
            raise ValueError("document_path must remain inside the manual-drop root")
        return candidate


class Assessment(BaseModel):
    recommendation: Literal["BUY_CANDIDATE", "WATCH", "PASS", "BLOCK"]
    rationale: str
    invalidating_fact: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    model_id: str
    prompt_version: str


class StrategyConfig(BaseModel):
    enabled: bool
    event_types: list[str]
    minimum_firmness_level: int = Field(ge=0, le=5)
    maximum_position_nav_pct: float = Field(ge=0, le=100)
    maximum_participation_pct: float = Field(gt=0, le=100)
    stop_loss_pct: float = Field(ge=0, le=100)
    time_stop_sessions: int = Field(ge=0)
    review_required: bool
    holding_horizon_sessions: int | None = None
    valuation_hurdle_max_pe_ratio: float | None = None


class FactExtraction(BaseModel):
    entity_name: str
    event_type: str
    firmness_level: int
    headline: str
    verbatim_quote: str
    counterparty: str | None = None
    contract_value_inr: float | None = None
    effective_date: str | None = None
    grounding_score: float = Field(ge=0.0, le=1.0)


class PaperOrder(BaseModel):
    order_id: str
    event_id: str
    strategy_id: str
    isin: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at_utc: datetime
    submitted_at_utc: datetime | None = None


class PaperFill(BaseModel):
    fill_id: str
    order_id: str
    isin: str
    symbol: str
    fill_price: float
    fill_quantity: int
    slippage_bps: float
    commission_inr: float
    stt_inr: float
    turnover_charges_inr: float
    gst_inr: float
    sebi_turnover_inr: float
    stamp_duty_inr: float
    total_cost_inr: float
    filled_at_utc: datetime


class PaperPosition(BaseModel):
    position_id: str
    strategy_id: str
    isin: str
    symbol: str
    status: PositionStatus
    quantity: int
    average_entry_price: float
    current_price: float
    unrealized_pnl_inr: float
    realized_pnl_inr: float
    opened_at_utc: datetime
    closed_at_utc: datetime | None = None
    exit_reason: str | None = None


class PortfolioSnapshot(BaseModel):
    timestamp_utc: datetime
    cash_inr: float
    total_equity_inr: float
    nav_inr: float
    open_positions_count: int
    daily_turnover_inr: float
    margin_utilized_inr: float


class ReconciliationResult(BaseModel):
    reconciliation_date: str
    status: Literal["RECONCILED", "DISCREPANCY_DETECTED"]
    dangling_orders_count: int
    unfilled_orders_count: int
    open_positions_count: int
    cash_balance_inr: float
    nav_inr: float
    discrepancies: list[str] = Field(default_factory=list)
