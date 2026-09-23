from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from qual_event_engine.events.service import ingest_event
from qual_event_engine.persistence.database import initialise
from qual_event_engine.sources.base import SourceCursor
from qual_event_engine.sources.exchange import (
    DEFAULT_NSE_API_URL,
    ExchangeAdapter,
    ExchangeConnector,
    NseAnnouncementFetcher,
    parse_nse_datetime,
)

FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "sources"
    / "nse_announcements_fixture.json"
)


# ---------------------------------------------------------------------------
# 1. Successful response parsing
# ---------------------------------------------------------------------------
def test_successful_live_response_parsing() -> None:
    fetcher = NseAnnouncementFetcher(fixture_path=FIXTURE_PATH)
    items = fetcher.fetch_announcements()
    assert len(items) == 3
    assert items[0]["seq_id"] == "106787497"
    assert items[0]["symbol"] == "TITAN"
    assert items[0]["desc"] == "Trading Window"
    assert items[1]["symbol"] == "BHEL"
    assert items[1]["desc"] == "Award of Order / Receipt of Order"


# ---------------------------------------------------------------------------
# 2. Empty response
# ---------------------------------------------------------------------------
def test_empty_response(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("[]", encoding="utf-8")
    fetcher = NseAnnouncementFetcher(fixture_path=empty_file)
    items = fetcher.fetch_announcements()
    assert items == []


# ---------------------------------------------------------------------------
# 3. Malformed response
# ---------------------------------------------------------------------------
def test_malformed_response(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"error": "not a list"}', encoding="utf-8")
    fetcher = NseAnnouncementFetcher(fixture_path=bad_file)
    with pytest.raises(ValueError, match="Malformed NSE response"):
        fetcher.fetch_announcements()


# ---------------------------------------------------------------------------
# 4. HTTP 429 backoff handling
# ---------------------------------------------------------------------------
def test_http_429_backoff() -> None:
    fetcher = NseAnnouncementFetcher(api_url="https://mock.test/429", max_retries=2, backoff_seconds=0.01)
    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = [{"seq_id": "1", "symbol": "TEST"}]

    with patch("httpx.Client.get", side_effect=[mock_resp_429, mock_resp_200]):
        items = fetcher.fetch_announcements()
        assert len(items) == 1
        assert items[0]["symbol"] == "TEST"


# ---------------------------------------------------------------------------
# 5. HTTP 500 failure
# ---------------------------------------------------------------------------
def test_http_500_failure() -> None:
    fetcher = NseAnnouncementFetcher(api_url="https://mock.test/500", max_retries=2, backoff_seconds=0.01)
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=mock_resp_500)

    with patch("httpx.Client.get", return_value=mock_resp_500):
        with pytest.raises(RuntimeError, match="Failed to fetch live NSE announcements"):
            fetcher.fetch_announcements()


# ---------------------------------------------------------------------------
# 6. Timeout handling
# ---------------------------------------------------------------------------
def test_timeout_handling() -> None:
    fetcher = NseAnnouncementFetcher(api_url="https://mock.test/timeout", max_retries=2, backoff_seconds=0.01)
    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Connection timed out")):
        with pytest.raises(RuntimeError, match="Failed to fetch live NSE announcements"):
            fetcher.fetch_announcements()


# ---------------------------------------------------------------------------
# 7. Duplicate announcement prevention within batch (Case A)
# ---------------------------------------------------------------------------
def test_duplicate_announcement_prevention(tmp_path: Path) -> None:
    dupe_file = tmp_path / "dupes.json"
    raw_item = {
        "seq_id": "9999",
        "symbol": "INFY",
        "sm_isin": "INE009A01021",
        "sm_name": "Infosys Ltd",
        "desc": "Updates",
        "attchmntText": "Headline",
        "sort_date": "2026-09-22 14:00:00",
    }
    # Item repeated twice in same payload
    dupe_file.write_text(json.dumps([raw_item, raw_item]), encoding="utf-8")

    fetcher = NseAnnouncementFetcher(fixture_path=dupe_file)
    connector = ExchangeConnector(drop_root=tmp_path, mode="LIVE_POLL", fetcher=fetcher)
    events = list(connector.events())
    assert len(events) == 1
    assert events[0].source_native_id == "9999"


# ---------------------------------------------------------------------------
# 8. Repeated polling idempotency (Case B)
# ---------------------------------------------------------------------------
def test_repeated_polling_idempotency(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialise(db_path)
    archive_root = tmp_path / "raw_archive"
    drop_root = tmp_path / "manual_drop"

    fetcher = NseAnnouncementFetcher(fixture_path=FIXTURE_PATH)
    connector = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher)

    # Cycle 1: ingest all events
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        inserted_1 = 0
        skipped_1 = 0
        for event in connector.events():
            _, created = ingest_event(conn, event, "exchange", drop_root, archive_root, "job-1")
            inserted_1 += int(created)
            skipped_1 += int(not created)
        conn.commit()

    assert inserted_1 == 3
    assert skipped_1 == 0

    # Cycle 2: poll again with same source data -> 0 new, 3 skipped
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        inserted_2 = 0
        skipped_2 = 0
        for event in connector.events():
            _, created = ingest_event(conn, event, "exchange", drop_root, archive_root, "job-2")
            inserted_2 += int(created)
            skipped_2 += int(not created)
        conn.commit()

    assert inserted_2 == 0
    assert skipped_2 == 3


# ---------------------------------------------------------------------------
# 9. Changed revision handling (Case C)
# ---------------------------------------------------------------------------
def test_changed_revision_handling(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialise(db_path)
    archive_root = tmp_path / "raw_archive"
    drop_root = tmp_path / "manual_drop"

    # Original announcement
    f1 = tmp_path / "v1.json"
    item_v1 = {
        "seq_id": "777",
        "symbol": "TCS",
        "sm_isin": "INE467B01029",
        "sm_name": "Tata Consultancy Services",
        "desc": "Outcome of Board Meeting",
        "attchmntText": "Board approves dividend of INR 28",
        "sort_date": "2026-09-22 10:00:00",
    }
    f1.write_text(json.dumps([item_v1]), encoding="utf-8")

    fetcher1 = NseAnnouncementFetcher(fixture_path=f1)
    connector1 = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher1)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for ev in connector1.events():
            ingest_event(conn, ev, "exchange", drop_root, archive_root, "job-v1")
        conn.commit()

    # Amended announcement (same seq_id, modified headline / document payload)
    f2 = tmp_path / "v2.json"
    item_v2 = dict(item_v1)
    item_v2["attchmntText"] = "Corrigendum: Board approves revised dividend of INR 30"
    f2.write_text(json.dumps([item_v2]), encoding="utf-8")

    fetcher2 = NseAnnouncementFetcher(fixture_path=f2)
    connector2 = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher2)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        created_events = 0
        for ev in connector2.events():
            _, created = ingest_event(conn, ev, "exchange", drop_root, archive_root, "job-v2")
            created_events += int(created)
        conn.commit()

        # Both observations should exist for the same native ID with distinct hashes
        rows = conn.execute(
            "SELECT observation_id, raw_sha256 FROM source_observation WHERE source_native_id='777'"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["raw_sha256"] != rows[1]["raw_sha256"]


# ---------------------------------------------------------------------------
# 10. Missing source-native ID deterministic fallback (Case D)
# ---------------------------------------------------------------------------
def test_missing_source_native_id_fallback(tmp_path: Path) -> None:
    item = {
        "seq_id": None,  # Missing ID
        "symbol": "RELIANCE",
        "desc": "Press Release",
        "attchmntText": "RIL commissions new green energy giga complex",
        "sort_date": "2026-09-22 12:00:00",
    }
    fetcher = NseAnnouncementFetcher()
    event = fetcher.item_to_manual_event(item, tmp_path)
    assert event.source_native_id.startswith("NSE_")
    assert len(event.source_native_id) == 20  # "NSE_" + 16 hex chars

    # Re-running on same item yields exact same deterministic fallback ID
    event2 = fetcher.item_to_manual_event(item, tmp_path)
    assert event2.source_native_id == event.source_native_id


# ---------------------------------------------------------------------------
# 11. Timestamp extraction: IST to UTC conversion
# ---------------------------------------------------------------------------
def test_timestamp_extraction_utc() -> None:
    dt1 = parse_nse_datetime("2026-09-22 14:38:32")
    assert dt1.tzinfo is not None
    assert dt1.hour == 9
    assert dt1.minute == 8
    assert dt1.second == 32
    assert dt1.isoformat() == "2026-09-22T09:08:32+00:00"

    dt2 = parse_nse_datetime("22-Sep-2026 14:38:32")
    assert dt2.isoformat() == "2026-09-22T09:08:32+00:00"


# ---------------------------------------------------------------------------
# 12. Archive failure stops downstream processing
# ---------------------------------------------------------------------------
def test_archive_failure_stops_downstream(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialise(db_path)
    drop_root = tmp_path / "manual_drop"
    invalid_archive_root = tmp_path / "non_existent_archive_root" / "blocked"

    # Make archive root uncreatable by writing a regular file at the parent
    parent_file = tmp_path / "non_existent_archive_root"
    parent_file.write_text("blocking file", encoding="utf-8")

    fetcher = NseAnnouncementFetcher(fixture_path=FIXTURE_PATH)
    connector = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher)
    event = next(iter(connector.events()))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises((OSError, ValueError)):
            ingest_event(conn, event, "exchange", drop_root, invalid_archive_root, "job-err")

        # Verify nothing entered source_observation
        count = conn.execute("SELECT count(*) FROM source_observation").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# 13. Provenance record creation
# ---------------------------------------------------------------------------
def test_provenance_creation(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialise(db_path)
    archive_root = tmp_path / "raw_archive"
    drop_root = tmp_path / "manual_drop"

    fetcher = NseAnnouncementFetcher(fixture_path=FIXTURE_PATH)
    connector = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        event = next(iter(connector.events()))
        _, created = ingest_event(conn, event, "exchange", drop_root, archive_root, "job-prov")
        conn.commit()

        assert created is True
        obs = conn.execute(
            "SELECT * FROM source_observation WHERE source_native_id=?",
            (event.source_native_id,),
        ).fetchone()
        assert obs is not None
        assert obs["source_id"] == "exchange"
        assert obs["source_native_id"] == "106787497"
        assert obs["source_published_at_utc"] == "2026-09-22T09:08:32+00:00"
        assert obs["system_first_seen_at_utc"] is not None
        assert len(obs["raw_sha256"]) == 64


# ---------------------------------------------------------------------------
# 14. Manifest fallback mode
# ---------------------------------------------------------------------------
def test_manifest_fallback_mode(tmp_path: Path) -> None:
    drop_root = tmp_path / "manual_drop"
    exch_drop = drop_root / "exchange"
    exch_drop.mkdir(parents=True)
    doc_path = exch_drop / "fallback.pdf"
    doc_path.write_bytes(b"%PDF-1.4 sample fallback document")

    manifest_file = exch_drop / "manifest.jsonl"
    manifest_record = {
        "source_native_id": "FALLBACK-001",
        "source_url": "https://nseindia.com/fallback.pdf",
        "source_published_at_utc": "2026-09-22T10:00:00Z",
        "document_path": "fallback.pdf",
        "event_type": "CORPORATE_UPDATE",
        "symbol": "TITAN",
        "legal_name": "Titan Company Limited",
        "headline": "Fallback manifest headline",
        "event_status": "ANNOUNCED",
        "firmness_level": 3,
    }
    manifest_file.write_text(json.dumps(manifest_record) + "\n", encoding="utf-8")

    # Connector instantiated in MANIFEST_DROP mode
    connector = ExchangeConnector(drop_root=drop_root, mode="MANIFEST_DROP")
    events = list(connector.events())
    assert len(events) == 1
    assert events[0].source_native_id == "FALLBACK-001"
    assert events[0].symbol == "TITAN"


# ---------------------------------------------------------------------------
# 15. LIVE_POLL configuration toggle
# ---------------------------------------------------------------------------
def test_live_poll_configuration_toggle(tmp_path: Path) -> None:
    adapter = ExchangeAdapter(drop_root=tmp_path, mode="LIVE_POLL")
    assert adapter.mode == "LIVE_POLL"

    adapter_manifest = ExchangeAdapter(drop_root=tmp_path, mode="MANIFEST_DROP")
    assert adapter_manifest.mode == "MANIFEST_DROP"


# ---------------------------------------------------------------------------
# 16. Complete End-to-End Integration: fetch -> archive -> provenance -> dedup
# ---------------------------------------------------------------------------
def test_complete_integration_pipeline(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    initialise(db_path)
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"

    fetcher = NseAnnouncementFetcher(fixture_path=FIXTURE_PATH)
    connector = ExchangeConnector(drop_root=drop_root, mode="LIVE_POLL", fetcher=fetcher)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        job_id = f"job-{uuid4()}"
        events = list(connector.events())
        assert len(events) == 3

        # Step 1: Ingest all events
        for ev in events:
            ev_id, created = ingest_event(conn, ev, "exchange", drop_root, archive_root, job_id)
            assert created is True
            assert ev_id is not None
        conn.commit()

        # Step 2: Verify Raw Documents in database and on disk
        raw_docs = conn.execute("SELECT * FROM raw_document").fetchall()
        assert len(raw_docs) == 3
        for doc in raw_docs:
            p = Path(doc["local_path"])
            assert p.exists()
            assert p.stat().st_size == doc["bytes"]

        # Step 3: Verify Source Observations
        obs_rows = conn.execute("SELECT * FROM source_observation").fetchall()
        assert len(obs_rows) == 3

        # Step 4: Verify Canonical Events
        events_rows = conn.execute("SELECT * FROM canonical_event").fetchall()
        assert len(events_rows) == 3
        symbols = {r["symbol"] for r in events_rows}
        assert symbols == {"TITAN", "BHEL", "INFY"}

        # Step 5: Verify Idempotent Dedup
        for ev in events:
            _, created = ingest_event(conn, ev, "exchange", drop_root, archive_root, job_id)
            assert created is False
        conn.commit()

        # Counts must remain exactly 3
        assert conn.execute("SELECT count(*) FROM raw_document").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM source_observation").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM canonical_event").fetchone()[0] == 3
