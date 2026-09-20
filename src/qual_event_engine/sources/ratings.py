from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from qual_event_engine.domain.models import ManualEvent
from qual_event_engine.ingestion.manual import load_manifest
from qual_event_engine.sources.base import SourceConnector, StandardSourceAdapter


class RatingsAdapter(StandardSourceAdapter):
    """Adapter for Credit Rating Agency disclosures (§5.2, §29.1)."""

    source_id = "ratings"

    def __init__(
        self,
        base_url: str = "https://www.crisil.com/en/home/our-businesses/ratings/rating-actions.html",
        drop_root: Path | None = None,
    ) -> None:
        super().__init__(base_url=base_url, drop_root=drop_root)


class RatingsConnector(SourceConnector):
    """Connector for Credit Rating Agency disclosures: CRISIL, ICRA, CARE, India Ratings (§5.2)."""

    source_id = "ratings"

    def __init__(self, drop_root: Path) -> None:
        self._drop_root = drop_root

    def events(self) -> Iterable[ManualEvent]:
        return load_manifest(self._drop_root, self.source_id)
