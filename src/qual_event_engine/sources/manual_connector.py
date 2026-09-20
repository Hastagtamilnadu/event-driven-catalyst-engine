from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from qual_event_engine.domain.models import ManualEvent
from qual_event_engine.ingestion.manual import load_manifest
from qual_event_engine.sources.base import SourceConnector


class PermittedFeedConnector(SourceConnector):
    """Connector for source data collected by the operator through permitted access."""

    def __init__(self, source_id: str, manual_drop_root: Path) -> None:
        self.source_id = source_id
        self._manual_drop_root = manual_drop_root

    def events(self) -> Iterable[ManualEvent]:
        return load_manifest(self._manual_drop_root, self.source_id)
