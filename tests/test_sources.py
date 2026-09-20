from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from qual_event_engine.sources.base import (
    RawSourceItem,
    SourceAdapter,
    SourceCursor,
)
from qual_event_engine.sources.registry import (
    VALID_ADAPTERS,
    get_adapter,
    validate_source_id,
)


@pytest.mark.parametrize("source_id", list(VALID_ADAPTERS.keys()))
def test_all_sources_registered_and_constructible(source_id: str) -> None:
    validated = validate_source_id(source_id)
    assert validated == source_id
    adapter = get_adapter(source_id)
    assert isinstance(adapter, SourceAdapter)
    assert adapter.source_id == source_id


@pytest.mark.parametrize("source_id", list(VALID_ADAPTERS.keys()))
def test_source_adapter_normalisation_and_validation(source_id: str, tmp_path: Path) -> None:
    adapter = get_adapter(source_id, drop_root=tmp_path)

    # Test with inline payload
    item = RawSourceItem(
        source_id=source_id,
        native_id=f"{source_id}-test-001",
        url=f"https://example.test/{source_id}/doc1",
        published_at_utc="2026-03-15T09:00:00Z",
        payload={"sample_key": "sample_val", "source": source_id},
    )

    draft = adapter.normalise(item)
    assert draft.source_id == source_id
    assert draft.source_native_id == f"{source_id}-test-001"
    assert len(draft.document_hash) == 64
    assert draft.mime_type == "application/json"
    assert draft.file_size_bytes > 0

    val_result = adapter.validate(draft)
    assert val_result.valid is True
    assert val_result.error_message is None

    # Test cursor advance
    cursor = SourceCursor(source_id=source_id, cursor_value="", updated_at_utc="")
    res = asyncio.run(adapter.fetch(cursor))
    next_c = adapter.next_cursor(res)
    assert isinstance(next_c, SourceCursor)
    assert next_c.source_id == source_id


@pytest.mark.parametrize("source_id", list(VALID_ADAPTERS.keys()))
def test_source_adapter_with_drop_fixture(source_id: str, tmp_path: Path) -> None:
    # Set up drop root with manifest and file
    source_drop = tmp_path / source_id
    source_drop.mkdir(parents=True)
    doc_file = source_drop / "doc.pdf"
    # PDF magic bytes %PDF
    doc_file.write_bytes(b"%PDF-1.4\n%test pdf content\n%%EOF")

    manifest_line = {
        "source_native_id": f"{source_id}-doc-99",
        "source_url": f"https://example.test/{source_id}/doc.pdf",
        "source_published_at_utc": "2026-03-15T10:30:00Z",
        "document_path": "doc.pdf",
        "event_type": "TEST_EVENT",
    }
    (source_drop / "manifest.jsonl").write_text(json.dumps(manifest_line) + "\n", encoding="utf-8")

    adapter = get_adapter(source_id, drop_root=tmp_path)
    cursor = SourceCursor(source_id=source_id, cursor_value="2026-03-15T00:00:00Z", updated_at_utc="")
    fetch_result = asyncio.run(adapter.fetch(cursor))

    assert len(fetch_result.items) == 1
    fetched_item = fetch_result.items[0]
    assert fetched_item.native_id == f"{source_id}-doc-99"

    draft = adapter.normalise(fetched_item)
    assert draft.mime_type == "application/pdf"
    assert len(draft.document_hash) == 64
    assert draft.file_size_bytes > 0

    val_result = adapter.validate(draft)
    assert val_result.valid is True


@pytest.mark.parametrize("source_id", list(VALID_ADAPTERS.keys()))
def test_source_adapter_health_check(source_id: str, tmp_path: Path) -> None:
    # In test environment, health check tests connectivity with verify=True and fallback to drop_root
    adapter = get_adapter(source_id, drop_root=tmp_path)
    health = asyncio.run(adapter.health_check())
    assert health.source_id == source_id
    assert health.status in ("OK", "DEGRADED", "DOWN")
    assert health.latency_ms >= 0.0
    assert len(health.timestamp_utc) > 0


def test_tls_verification_is_strictly_enforced() -> None:
    # Verify that StandardSourceAdapter does not allow or use verify=False
    import inspect

    from qual_event_engine.sources import base
    source_code = inspect.getsource(base.StandardSourceAdapter.health_check)
    assert "verify=True" in source_code
    assert "verify=False" not in source_code
