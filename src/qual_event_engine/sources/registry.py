from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from qual_event_engine.sources.base import SourceAdapter, SourceConnector
from qual_event_engine.sources.calendar import CalendarAdapter, CalendarConnector
from qual_event_engine.sources.exchange import ExchangeAdapter, ExchangeConnector
from qual_event_engine.sources.ownership import OwnershipAdapter, OwnershipConnector
from qual_event_engine.sources.parivesh import PariveshAdapter, PariveshConnector
from qual_event_engine.sources.ratings import RatingsAdapter, RatingsConnector
from qual_event_engine.sources.surveillance import SurveillanceAdapter, SurveillanceConnector
from qual_event_engine.sources.tenders import TendersAdapter, TendersConnector
from qual_event_engine.sources.transcripts import TranscriptsAdapter, TranscriptsConnector
from qual_event_engine.sources.usfda import USFDAAdapter, USFDAConnector

VALID_SOURCES: dict[str, Callable[[Path], SourceConnector]] = {
    "exchange": ExchangeConnector,
    "ratings": RatingsConnector,
    "tenders": TendersConnector,
    "usfda": USFDAConnector,
    "parivesh": PariveshConnector,
    "transcripts": TranscriptsConnector,
    "ownership": OwnershipConnector,
    "surveillance": SurveillanceConnector,
    "calendar": CalendarConnector,
}

VALID_ADAPTERS: dict[str, Callable[..., SourceAdapter]] = {
    "exchange": ExchangeAdapter,
    "ratings": RatingsAdapter,
    "tenders": TendersAdapter,
    "usfda": USFDAAdapter,
    "parivesh": PariveshAdapter,
    "transcripts": TranscriptsAdapter,
    "ownership": OwnershipAdapter,
    "surveillance": SurveillanceAdapter,
    "calendar": CalendarAdapter,
}

SourceMode = Literal["PAPER_SIGNAL", "CONTEXT_ONLY", "ACTIVE_RISK_OVERLAY"]


def validate_source_id(source_id: str) -> str:
    canonical = source_id.strip().lower()
    if canonical not in VALID_SOURCES:
        choices = ", ".join(sorted(VALID_SOURCES))
        raise ValueError(f"Unknown source {source_id!r}. Expected one of: {choices}")
    return canonical


def get_connector(source_id: str, drop_root: Path) -> SourceConnector:
    canonical = validate_source_id(source_id)
    connector_cls = VALID_SOURCES[canonical]
    return connector_cls(drop_root)


def get_adapter(source_id: str, drop_root: Path | None = None) -> SourceAdapter:
    canonical = validate_source_id(source_id)
    adapter_cls = VALID_ADAPTERS[canonical]
    return adapter_cls(drop_root=drop_root)
