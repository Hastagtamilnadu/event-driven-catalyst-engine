from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DocumentProvenance:
    """Provenance record wired to §28 source_observation column set.

    All field names match the §28 DDL exactly.
    """

    # §28 required fields
    observation_id: str
    source_id: str
    source_native_id: str | None
    source_url: str
    source_published_at_utc: str | None
    source_document_date: str | None          # §28 — date from document header/metadata
    system_first_seen_at_utc: str
    downloaded_at_utc: str | None
    exchange_first_seen_at_utc: str | None
    raw_sha256: str | None
    retrieval_status: str                     # OK | FAILED | SKIPPED | DUPLICATE
    http_status: int | None                   # §28
    parser_version: str | None
    timezone_original: str | None             # §28 — timezone as declared in the document
    supersedes_observation_id: str | None     # §28 — links amended filing to original
    job_run_id: str

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        source_id: str,
        source_native_id: str | None,
        source_url: str,
        job_run_id: str,
        observation_id: str | None = None,
        source_published_at_utc: str | None = None,
        source_document_date: str | None = None,
        exchange_first_seen_at_utc: str | None = None,
        http_status: int | None = None,
        parser_version: str | None = None,
        timezone_original: str | None = None,
        supersedes_observation_id: str | None = None,
        downloaded_at_utc: datetime | None = None,
        retrieval_status: str = "OK",
    ) -> DocumentProvenance:
        sha = hashlib.sha256(data).hexdigest()
        now = datetime.now(UTC)
        ts_dl = (downloaded_at_utc or now).isoformat()
        ts_seen = now.isoformat()
        obs_id = observation_id or (source_id + ":" + sha)
        return cls(
            observation_id=obs_id,
            source_id=source_id,
            source_native_id=source_native_id,
            source_url=source_url,
            source_published_at_utc=source_published_at_utc,
            source_document_date=source_document_date,
            system_first_seen_at_utc=ts_seen,
            downloaded_at_utc=ts_dl,
            exchange_first_seen_at_utc=exchange_first_seen_at_utc,
            raw_sha256=sha,
            retrieval_status=retrieval_status,
            http_status=http_status,
            parser_version=parser_version,
            timezone_original=timezone_original,
            supersedes_observation_id=supersedes_observation_id,
            job_run_id=job_run_id,
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        source_id: str,
        source_native_id: str | None,
        source_url: str,
        job_run_id: str,
        **kwargs: Any,
    ) -> DocumentProvenance:
        data = path.read_bytes()
        return cls.from_bytes(
            data=data,
            source_id=source_id,
            source_native_id=source_native_id,
            source_url=source_url,
            job_run_id=job_run_id,
            **kwargs,
        )

    def to_db_row(self) -> dict[str, object]:
        """Return a dict matching the source_observation DDL column names exactly."""
        return {
            "observation_id": self.observation_id,
            "source_id": self.source_id,
            "source_native_id": self.source_native_id,
            "source_url": self.source_url,
            "source_published_at_utc": self.source_published_at_utc,
            "source_document_date": self.source_document_date,
            "system_first_seen_at_utc": self.system_first_seen_at_utc,
            "downloaded_at_utc": self.downloaded_at_utc,
            "exchange_first_seen_at_utc": self.exchange_first_seen_at_utc,
            "raw_sha256": self.raw_sha256,
            "retrieval_status": self.retrieval_status,
            "http_status": self.http_status,
            "parser_version": self.parser_version,
            "timezone_original": self.timezone_original,
            "supersedes_observation_id": self.supersedes_observation_id,
            "job_run_id": self.job_run_id,
        }
