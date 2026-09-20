from __future__ import annotations

import hashlib
import json
import mimetypes
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from qual_event_engine.domain.models import ManualEvent


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: str
    status: Literal["OK", "DEGRADED", "DOWN"]
    latency_ms: float
    message: str
    timestamp_utc: str


@dataclass(frozen=True, slots=True)
class SourceCursor:
    source_id: str
    cursor_value: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class RawSourceItem:
    source_id: str
    native_id: str
    url: str
    published_at_utc: str
    payload: dict[str, Any]
    document_bytes: bytes | None = None
    document_path: str | None = None


@dataclass(frozen=True, slots=True)
class SourceObservationDraft:
    source_id: str
    source_native_id: str
    source_url: str
    source_published_at_utc: str
    document_path: str
    document_hash: str
    mime_type: str
    file_size_bytes: int
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FetchResult:
    items: list[RawSourceItem]
    next_cursor: SourceCursor
    has_more: bool


class SourceAdapter(ABC):
    """Base source adapter implementing the Section 29.1 contract.

    Returns raw source metadata and document references. It cannot classify
    an event, call an AI model, or create a paper order.
    TLS certificate verification is strictly mandatory for all HTTP requests.
    """

    source_id: str

    @abstractmethod
    async def health_check(self) -> SourceHealth:
        """Verify upstream accessibility, latency, and TLS verification."""

    @abstractmethod
    async def fetch(self, cursor: SourceCursor) -> FetchResult:
        """Fetch raw items starting from the provided cursor."""

    @abstractmethod
    def normalise(self, item: RawSourceItem) -> SourceObservationDraft:
        """Normalise raw source item into a standard observation draft with hash and MIME detection."""

    @abstractmethod
    def validate(self, draft: SourceObservationDraft) -> ValidationResult:
        """Perform deterministic schema and integrity validation on the draft."""

    @abstractmethod
    def next_cursor(self, result: FetchResult) -> SourceCursor:
        """Derive the next monotonic cursor from fetch results."""


class StandardSourceAdapter(SourceAdapter):
    """Standard implementation of SourceAdapter adhering to Section 29.1 & 29.2."""

    source_id: str
    base_url: str
    drop_root: Path | None

    def __init__(self, base_url: str, drop_root: Path | None = None) -> None:
        self.base_url = base_url
        self.drop_root = drop_root

    async def health_check(self) -> SourceHealth:
        now_utc = datetime.now(UTC).isoformat()
        start = time.perf_counter()
        try:
            # Strictly enforce TLS certificate verification: verify=True, trust_env=False prevents malformed proxy env vars
            async with httpx.AsyncClient(verify=True, timeout=5.0, trust_env=False) as client:
                response = await client.get(self.base_url, follow_redirects=True)
                latency = (time.perf_counter() - start) * 1000.0
                # Any successful HTTP handshake (2xx, 3xx, 403 on portals blocking scrapers) verifies TLS and connectivity
                if response.status_code < 500:
                    return SourceHealth(
                        source_id=self.source_id,
                        status="OK",
                        latency_ms=round(latency, 2),
                        message=f"HTTP {response.status_code} TLS verified",
                        timestamp_utc=now_utc,
                    )
                return SourceHealth(
                    source_id=self.source_id,
                    status="DEGRADED",
                    latency_ms=round(latency, 2),
                    message=f"Upstream server error HTTP {response.status_code}",
                    timestamp_utc=now_utc,
                )
        except (httpx.HTTPError, OSError) as exc:
            latency = (time.perf_counter() - start) * 1000.0
            # If drop_root exists and has files, mark as DEGRADED rather than hard DOWN
            if self.drop_root and self.drop_root.exists():
                return SourceHealth(
                    source_id=self.source_id,
                    status="DEGRADED",
                    latency_ms=round(latency, 2),
                    message=f"Network check: {exc}. Local drop directory active.",
                    timestamp_utc=now_utc,
                )
            return SourceHealth(
                source_id=self.source_id,
                status="DOWN",
                latency_ms=round(latency, 2),
                message=f"Network unreachable: {exc}",
                timestamp_utc=now_utc,
            )

    async def fetch(self, cursor: SourceCursor) -> FetchResult:
        items: list[RawSourceItem] = []
        if self.drop_root and self.drop_root.exists():
            manifest_file = self.drop_root / self.source_id / "manifest.jsonl"
            if manifest_file.exists():
                with manifest_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        pub_time = data.get("source_published_at_utc", "")
                        if pub_time > cursor.cursor_value:
                            native_id = data.get("source_native_id", "")
                            url = data.get("source_url", "")
                            doc_path = data.get("document_path")
                            items.append(
                                RawSourceItem(
                                    source_id=self.source_id,
                                    native_id=native_id,
                                    url=url,
                                    published_at_utc=pub_time,
                                    payload=data,
                                    document_path=doc_path,
                                )
                            )
        return FetchResult(
            items=items,
            next_cursor=self.next_cursor(FetchResult(items=items, next_cursor=cursor, has_more=False)),
            has_more=False,
        )

    def normalise(self, item: RawSourceItem) -> SourceObservationDraft:
        content_bytes = item.document_bytes
        doc_path = item.document_path or ""
        if content_bytes is None and doc_path and self.drop_root:
            full_path = self.drop_root / self.source_id / doc_path
            if full_path.exists():
                content_bytes = full_path.read_bytes()

        if content_bytes is not None:
            content_hash = hashlib.sha256(content_bytes).hexdigest()
            file_size = len(content_bytes)
            # Detect MIME from magic bytes per §29.2
            if content_bytes.startswith(b"%PDF"):
                mime_type = "application/pdf"
            elif content_bytes.startswith((b"{", b"[")):
                mime_type = "application/json"
            elif content_bytes.startswith(b"PK\x03\x04"):
                mime_type = "application/zip"
            else:
                guessed, _ = mimetypes.guess_type(doc_path)
                mime_type = guessed or "application/octet-stream"
        else:
            payload_bytes = json.dumps(item.payload, sort_keys=True).encode("utf-8")
            content_hash = hashlib.sha256(payload_bytes).hexdigest()
            file_size = len(payload_bytes)
            mime_type = "application/json"

        return SourceObservationDraft(
            source_id=self.source_id,
            source_native_id=item.native_id,
            source_url=item.url,
            source_published_at_utc=item.published_at_utc,
            document_path=doc_path,
            document_hash=content_hash,
            mime_type=mime_type,
            file_size_bytes=file_size,
            raw_payload=item.payload,
        )

    def validate(self, draft: SourceObservationDraft) -> ValidationResult:
        if draft.source_id != self.source_id:
            return ValidationResult(
                valid=False,
                error_message=f"Source ID mismatch: expected {self.source_id}, got {draft.source_id}",
            )
        if not draft.source_native_id:
            return ValidationResult(valid=False, error_message="Missing source_native_id")
        if not draft.source_url:
            return ValidationResult(valid=False, error_message="Missing source_url")
        if not draft.source_published_at_utc:
            return ValidationResult(valid=False, error_message="Missing source_published_at_utc")
        if len(draft.document_hash) != 64:
            return ValidationResult(valid=False, error_message="Invalid SHA-256 document hash")
        if draft.file_size_bytes < 0:
            return ValidationResult(valid=False, error_message="Negative file size")

        warnings: list[str] = []
        if draft.file_size_bytes == 0:
            warnings.append("Document is zero bytes")
        return ValidationResult(valid=True, warnings=warnings)

    def next_cursor(self, result: FetchResult) -> SourceCursor:
        if not result.items:
            return result.next_cursor
        latest_time = max(item.published_at_utc for item in result.items)
        return SourceCursor(
            source_id=self.source_id,
            cursor_value=latest_time,
            updated_at_utc=datetime.now(UTC).isoformat(),
        )


class SourceConnector(ABC):
    """Boundary for operator-provided permitted source feeds.

    A connector validates and yields source records. It must not place orders,
    alter strategy configuration, or use evasion methods to access a source.
    """

    source_id: str

    @abstractmethod
    def events(self) -> Iterable[ManualEvent]:
        """Yield validated source events in first-seen order."""
