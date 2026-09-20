from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocumentProvenance:
    source_id: str
    source_native_id: str
    source_url: str
    sha256: str
    storage_path: str
    downloaded_at_utc: datetime
    content_length_bytes: int
    etag: str | None = None
    http_status: int = 200

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        source_id: str,
        source_native_id: str,
        source_url: str,
        storage_path: str,
        etag: str | None = None,
        http_status: int = 200,
        downloaded_at_utc: datetime | None = None,
    ) -> DocumentProvenance:
        sha256 = hashlib.sha256(data).hexdigest()
        ts = downloaded_at_utc or datetime.now(UTC)
        return cls(
            source_id=source_id,
            source_native_id=source_native_id,
            source_url=source_url,
            sha256=sha256,
            storage_path=storage_path,
            downloaded_at_utc=ts,
            content_length_bytes=len(data),
            etag=etag,
            http_status=http_status,
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        source_id: str,
        source_native_id: str,
        source_url: str,
        storage_rel_path: str,
    ) -> DocumentProvenance:
        data = path.read_bytes()
        return cls.from_bytes(
            data=data,
            source_id=source_id,
            source_native_id=source_native_id,
            source_url=source_url,
            storage_path=storage_rel_path,
        )
