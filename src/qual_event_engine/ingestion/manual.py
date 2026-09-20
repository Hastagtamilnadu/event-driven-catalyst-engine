from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from qual_event_engine.domain.models import ManualEvent


def manifest_path(drop_root: Path, source_id: str) -> Path:
    return drop_root / source_id / "manifest.jsonl"


def load_manifest(drop_root: Path, source_id: str) -> Iterator[ManualEvent]:
    path = manifest_path(drop_root, source_id)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing permitted-source manifest: {path}. "
            "Create a JSONL manifest and place documents under the manual-drop root."
        )
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield ManualEvent.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(f"Invalid manifest record at {path}:{line_number}: {exc}") from exc
