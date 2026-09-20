from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qual_event_engine.operations.hashing import sha256_file


@dataclass(frozen=True, slots=True)
class ArchivedDocument:
    sha256: str
    path: Path
    mime_type: str
    bytes: int
    archived_at_utc: str


def detect_mime(path: Path) -> str:
    header = path.read_bytes()[:16]
    if header.startswith(b"%PDF"):
        return "application/pdf"
    if header.startswith(b"PK"):
        return "application/zip"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def archive_document(source_id: str, source_file: Path, archive_root: Path) -> ArchivedDocument:
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Source document does not exist: {source_file}")
    digest = sha256_file(source_file)
    suffix = source_file.suffix.lower() or ".bin"
    now = datetime.now(UTC)
    destination = (
        archive_root / source_id / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    )
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{digest}{suffix}"
    if not target.exists():
        shutil.copy2(source_file, target)
    return ArchivedDocument(
        sha256=digest,
        path=target,
        mime_type=detect_mime(target),
        bytes=target.stat().st_size,
        archived_at_utc=now.isoformat(),
    )
