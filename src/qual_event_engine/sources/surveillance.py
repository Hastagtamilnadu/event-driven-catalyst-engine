from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from qual_event_engine.domain.models import ManualEvent
from qual_event_engine.ingestion.manual import load_manifest
from qual_event_engine.sources.base import SourceConnector, StandardSourceAdapter


class SurveillanceAdapter(StandardSourceAdapter):
    """Adapter for Regulatory Actions, ASM, ESM, and Forensic Audits (§5.8, §29.1)."""

    source_id = "surveillance"

    def __init__(
        self,
        base_url: str = "https://www.nseindia.com/reports/surveillance",
        drop_root: Path | None = None,
    ) -> None:
        super().__init__(base_url=base_url, drop_root=drop_root)


class SurveillanceConnector(SourceConnector):
    """Connector for Regulatory Actions, ASM, ESM, and Forensic Audits (§5.8)."""

    source_id = "surveillance"

    def __init__(self, drop_root: Path) -> None:
        self._drop_root = drop_root

    def events(self) -> Iterable[ManualEvent]:
        return load_manifest(self._drop_root, self.source_id)
