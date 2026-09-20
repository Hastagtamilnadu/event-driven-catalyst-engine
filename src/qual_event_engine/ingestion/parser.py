from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    page_count: int | None
    extraction_quality: str
    parser_status: str


def parse_document(path: Path, mime_type: str) -> ParsedDocument:
    if mime_type == "application/pdf":
        try:
            with fitz.open(path) as document:
                pages = [page.get_text("text") for page in document]
            text = "\n".join(pages).strip()
            quality = "GOOD" if len(text) >= 500 else "OCR_REQUIRED"
            return ParsedDocument(text, len(pages), quality, "PARSED")
        except (fitz.FileDataError, RuntimeError):
            return ParsedDocument("", None, "UNSUPPORTED", "FAILED")
    if mime_type.startswith("text/") or path.suffix.lower() in {".json", ".jsonl", ".csv", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        quality = "GOOD" if text else "PARTIAL"
        return ParsedDocument(text, 1, quality, "PARSED")
    return ParsedDocument("", None, "UNSUPPORTED", "SKIPPED")
