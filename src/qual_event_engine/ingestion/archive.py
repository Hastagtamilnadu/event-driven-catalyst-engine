from __future__ import annotations

"""§29.2 Archive workflow — all 9 required steps.

Step 1:  Validate TLS and HTTP status.
Step 2:  Check size against source minimum and maximum.
Step 3:  Detect MIME type from bytes, not filename alone.
Step 4:  Hash bytes with SHA-256.
Step 5:  Archive to raw_archive/source_id/YYYY/MM/DD/hash.ext.
Step 6:  Save raw_document and source_observation in one transaction.
Step 7:  Extract text with PyMuPDF.
Step 8:  Record page count, extracted_characters, and extraction_quality.
Step 9:  Route poor-quality scans to OCR_REQUIRED or manual review.
"""

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# §29.3 parser-quality states — exact names from artifact
QUALITY_GOOD = "GOOD"
QUALITY_PARTIAL = "PARTIAL"
QUALITY_OCR_REQUIRED = "OCR_REQUIRED"
QUALITY_UNSUPPORTED = "UNSUPPORTED"
QUALITY_MALICIOUS = "MALICIOUS"           # §29.3 — security scan fails

# Thresholds for quality routing
_MIN_CHARS_PER_PAGE_GOOD = 200
_MIN_CHARS_PER_PAGE_OCR = 10


@dataclass
class ArchivedDocument:
    sha256: str
    path: Path
    mime_type: str
    bytes: int
    page_count: int | None
    extracted_characters: int | None
    extraction_quality: str              # §29.3 state
    archived_at_utc: str
    malware_scan_status: str             # §28 raw_document column
    parser_status: str


def _detect_mime_from_bytes(data: bytes, filename: str = "") -> str:
    """Step 3 — detect MIME from file bytes, not filename alone."""
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:2] == b"PK":
        return "application/zip"
    if data[:5] in (b"<html", b"<!DOC", b"<?xml"):
        return "text/html"
    if data[:1] == b"{":
        return "application/json"
    # Fallback: inspect extension as last resort only
    if filename.endswith(".pdf"):
        return "application/pdf"
    if filename.endswith((".html", ".htm")):
        return "text/html"
    return "application/octet-stream"


def _sha256_bytes(data: bytes) -> str:
    """Step 4 — SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _malware_scan(data: bytes) -> str:
    """Stub security scan. Returns CLEAN or MALICIOUS.
    Production: replace with ClamAV / antivirus integration.
    Returns MALICIOUS when known-bad magic bytes are detected.
    """
    # Detect obvious malicious patterns
    bad_markers = [b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"]
    for marker in bad_markers:
        if marker in data:
            return "MALICIOUS"
    return "CLEAN"


def _extract_text_pymupdf(path: Path) -> tuple[int, int, str]:
    """Step 7–9 — extract text with PyMuPDF, returning (page_count, chars, quality).

    §29.3 quality routing:
    - GOOD:         chars/page >= _MIN_CHARS_PER_PAGE_GOOD
    - PARTIAL:      some pages readable
    - OCR_REQUIRED: chars/page < _MIN_CHARS_PER_PAGE_OCR (likely scanned)
    - UNSUPPORTED:  cannot open at all
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # PyMuPDF not installed — cannot extract; mark UNSUPPORTED
        return 0, 0, QUALITY_UNSUPPORTED

    try:
        doc = fitz.open(str(path))
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return 0, 0, QUALITY_UNSUPPORTED
        total_chars = 0
        readable_pages = 0
        for page in doc:
            text = page.get_text()
            pc = len(text.strip())
            total_chars += pc
            if pc >= _MIN_CHARS_PER_PAGE_GOOD:
                readable_pages += 1
        doc.close()
        chars_per_page = total_chars / page_count
        if chars_per_page >= _MIN_CHARS_PER_PAGE_GOOD:
            quality = QUALITY_GOOD
        elif chars_per_page >= _MIN_CHARS_PER_PAGE_OCR:
            quality = QUALITY_PARTIAL
        else:
            quality = QUALITY_OCR_REQUIRED
        return page_count, total_chars, quality
    except Exception:  # noqa: BLE001
        return 0, 0, QUALITY_UNSUPPORTED


def archive_document(
    source_id: str,
    source_file: Path,
    archive_root: Path,
    *,
    http_status: int | None = None,
    tls_verified: bool = True,
    source_min_bytes: int = 1,
    source_max_bytes: int = 50_000_000,
    observation_id: str | None = None,
    source_url: str = "",
    job_run_id: str = "",
    connection: sqlite3.Connection | None = None,
) -> ArchivedDocument:
    """Execute §29.2 archive workflow steps 1–9.

    Parameters
    ----------
    connection:
        If provided, step 6 persists raw_document and source_observation
        in a single transaction. If None, persistence is deferred to caller.
    """
    # -----------------------------------------------------------------
    # Step 1 — Validate TLS and HTTP status
    # -----------------------------------------------------------------
    if not tls_verified:
        raise ValueError(
            "TLS certificate verification disabled. "
            "Per §29, production adapters must not disable TLS."
        )
    if http_status is not None and http_status not in (200, 201, 206):
        raise ValueError(
            "HTTP status " + str(http_status) + " is not a success status. "
            "Archive rejected."
        )

    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError("Source document does not exist: " + str(source_file))

    data = source_file.read_bytes()

    # -----------------------------------------------------------------
    # Step 2 — Check size against source minimum and maximum
    # -----------------------------------------------------------------
    size = len(data)
    if size < source_min_bytes:
        raise ValueError(
            "Document size " + str(size) + " bytes is below source minimum "
            + str(source_min_bytes) + " bytes."
        )
    if size > source_max_bytes:
        raise ValueError(
            "Document size " + str(size) + " bytes exceeds source maximum "
            + str(source_max_bytes) + " bytes."
        )

    # -----------------------------------------------------------------
    # Step 3 — Detect MIME type from bytes, not filename alone
    # -----------------------------------------------------------------
    mime_type = _detect_mime_from_bytes(data, source_file.name)
    if mime_type == "application/octet-stream":
        quality = QUALITY_UNSUPPORTED
        page_count, extracted_characters = None, None
    else:
        quality = None  # determined later in step 9

    # -----------------------------------------------------------------
    # Security scan (§29.3 MALICIOUS state)
    # -----------------------------------------------------------------
    malware_status = _malware_scan(data)
    if malware_status == "MALICIOUS":
        raise ValueError(
            "Security scan FAILED for document: " + str(source_file)
            + ". Document quarantined. Not archived."
        )

    # -----------------------------------------------------------------
    # Step 4 — Hash bytes with SHA-256
    # -----------------------------------------------------------------
    digest = _sha256_bytes(data)

    # -----------------------------------------------------------------
    # Step 5 — Archive to raw_archive/source_id/YYYY/MM/DD/hash.ext
    # -----------------------------------------------------------------
    now = datetime.now(UTC)
    suffix = source_file.suffix.lower() or ".bin"
    destination = (
        archive_root
        / source_id
        / now.strftime("%Y")
        / now.strftime("%m")
        / now.strftime("%d")
    )
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (digest + suffix)
    if not target.exists():
        shutil.copy2(source_file, target)

    # -----------------------------------------------------------------
    # Step 7 — Extract text with PyMuPDF
    # Step 8 — Record page count, extracted_characters, extraction_quality
    # Step 9 — Route poor-quality scans
    # -----------------------------------------------------------------
    if mime_type == "application/pdf":
        page_count, extracted_characters, quality = _extract_text_pymupdf(target)
    elif quality is None:
        # Non-PDF: HTML/JSON are inherently readable
        page_count = 1
        extracted_characters = len(data)
        quality = QUALITY_GOOD

    archived_doc = ArchivedDocument(
        sha256=digest,
        path=target,
        mime_type=mime_type,
        bytes=size,
        page_count=page_count,
        extracted_characters=extracted_characters,
        extraction_quality=quality,
        archived_at_utc=now.isoformat(),
        malware_scan_status=malware_status,
        parser_status=quality,
    )

    # -----------------------------------------------------------------
    # Step 6 — Save raw_document and source_observation in ONE transaction
    # -----------------------------------------------------------------
    if connection is not None:
        _persist_in_transaction(connection, archived_doc, observation_id, source_url, job_run_id, source_id)

    return archived_doc


def _persist_in_transaction(
    connection: sqlite3.Connection,
    doc: ArchivedDocument,
    observation_id: str | None,
    source_url: str,
    job_run_id: str,
    source_id: str,
) -> None:
    """Step 6 — atomic: insert raw_document + source_observation together."""
    obs_id = observation_id or (source_id + ":" + doc.sha256)
    now = datetime.now(UTC).isoformat()

    connection.execute(
        """
        INSERT OR IGNORE INTO raw_document
          (raw_sha256, local_path, mime_type, bytes, page_count,
           extracted_characters, extraction_quality, archived_at_utc,
           malware_scan_status, parser_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            doc.sha256,
            str(doc.path),
            doc.mime_type,
            doc.bytes,
            doc.page_count,
            doc.extracted_characters,
            doc.extraction_quality,
            doc.archived_at_utc,
            doc.malware_scan_status,
            doc.parser_status,
        ),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO source_observation
          (observation_id, source_id, source_url, system_first_seen_at_utc,
           downloaded_at_utc, raw_sha256, retrieval_status, job_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            obs_id,
            source_id,
            source_url,
            now,
            now,
            doc.sha256,
            "OK",
            job_run_id,
        ),
    )
