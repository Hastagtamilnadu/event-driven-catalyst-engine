from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from qual_event_engine.domain.models import ManualEvent
from qual_event_engine.ingestion.archive import archive_document
from qual_event_engine.ingestion.parser import parse_document
from qual_event_engine.market.reference import latest_fundamental
from qual_event_engine.persistence.repositories import json_value


def _now() -> str:
    return datetime.now(UTC).isoformat()


def materiality(value: float | None, revenue: float | None) -> float | None:
    if value is None or revenue is None or revenue <= 0:
        return None
    return value / revenue


def ingest_event(
    connection: sqlite3.Connection,
    event: ManualEvent,
    source_id: str,
    drop_root: Path,
    archive_root: Path,
    job_run_id: str,
) -> tuple[str, bool]:
    source_file = event.source_file(drop_root)
    archived = archive_document(source_id, source_file, archive_root)
    parsed = parse_document(archived.path, archived.mime_type)
    existing = connection.execute(
        """SELECT observation_id FROM source_observation
           WHERE source_id=? AND source_native_id=? AND raw_sha256=?""",
        (source_id, event.source_native_id, archived.sha256),
    ).fetchone()
    if existing:
        event_row = connection.execute(
            "SELECT event_id FROM canonical_event WHERE observation_id=?", (existing["observation_id"],)
        ).fetchone()
        ret_id = str(event_row["event_id"]) if event_row else str(existing["observation_id"])
        return ret_id, False

    observation_id = str(uuid4())
    event_id = str(uuid4())
    now = _now()
    ttm_revenue = event.ttm_revenue_inr or latest_fundamental(
        connection, event.symbol, "TTM_REVENUE_INR", event.source_published_at_utc
    )
    connection.execute(
        """INSERT INTO raw_document(
          raw_sha256,local_path,mime_type,bytes,page_count,extracted_characters,
          extraction_quality,archived_at_utc,parser_status
        ) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(raw_sha256) DO NOTHING""",
        (
            archived.sha256,
            str(archived.path),
            archived.mime_type,
            archived.bytes,
            parsed.page_count,
            len(parsed.text),
            parsed.extraction_quality,
            archived.archived_at_utc,
            parsed.parser_status,
        ),
    )
    connection.execute(
        """INSERT INTO source_observation(
          observation_id,source_id,source_native_id,source_url,source_published_at_utc,
          exchange_first_seen_at_utc,system_first_seen_at_utc,downloaded_at_utc,raw_sha256,retrieval_status,
          parser_version,job_run_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            observation_id,
            source_id,
            event.source_native_id,
            str(event.source_url),
            event.source_published_at_utc.astimezone(UTC).isoformat(),
            event.exchange_first_seen_at_utc.astimezone(UTC).isoformat()
            if event.exchange_first_seen_at_utc
            else None,
            now,
            now,
            archived.sha256,
            "ARCHIVED",
            "pymupdf-1",
            job_run_id,
        ),
    )
    entity_status = "VERIFIED" if event.entity_verified else "NEEDS_ENTITY_REVIEW"
    state = "INGESTED" if parsed.extraction_quality == "GOOD" else "BLOCKED_DOCUMENT"
    connection.execute(
        """INSERT INTO canonical_event(
          event_id,observation_id,isin,symbol,legal_name,sector,event_type,event_status,
          firmness_level,event_value_inr,ttm_revenue_inr,materiality_ratio,
          entity_match_status,event_state,headline,created_at_utc
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            event_id,
            observation_id,
            event.isin,
            event.symbol.upper(),
            event.legal_name,
            event.sector,
            event.event_type,
            event.event_status,
            event.firmness_level,
            event.event_value_inr,
            ttm_revenue,
            materiality(event.event_value_inr, ttm_revenue),
            entity_status,
            state,
            event.headline,
            now,
        ),
    )
    revision_id = str(uuid4())
    rev_cols = {str(r[0]) for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("event_revision",)).fetchall()}
    if rev_cols:
        r_fields = ["event_id", "observation_id", "revision_number", "revision_kind", "material_change_flag"]
        r_vals = [event_id, observation_id, 1, "ORIGINAL", 0]
        if "event_revision_id" in rev_cols:
            r_fields.insert(0, "event_revision_id")
            r_vals.insert(0, revision_id)
        if "revision_id" in rev_cols and "revision_id" not in r_fields:
            r_fields.insert(0, "revision_id")
            r_vals.insert(0, revision_id)
        if "new_value_json" in rev_cols:
            r_fields.append("new_value_json")
            r_vals.append("{}")
        if "reason" in rev_cols:
            r_fields.append("reason")
            r_vals.append("INITIAL")
        if "revised_by" in rev_cols:
            r_fields.append("revised_by")
            r_vals.append("SYSTEM")
        if "revised_at_utc" in rev_cols:
            r_fields.append("revised_at_utc")
            r_vals.append(now)
        if "revised_field" in rev_cols:
            r_fields.append("revised_field")
            r_vals.append("INITIAL")
        connection.execute(
            f"INSERT INTO event_revision({','.join(r_fields)}) VALUES({','.join('?' for _ in r_fields)})",
            r_vals,
        )

    fact_cols = {str(r[0]) for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("extracted_fact",)).fetchall()}
    fact_values = {
        "source_metadata": event.model_dump(mode="json"),
        "document_text": parsed.text,
        "previous_rating": event.previous_rating,
        "new_rating": event.new_rating,
        "counterparty": event.counterparty,
    }
    for field, value in fact_values.items():
        if value is None:
            continue
        fact_id = str(uuid4())
        f_fields = ["fact_id", "field_name", "value_json", "evidence_text", "page_number", "extractor_name", "extractor_version", "confidence", "validation_status"]
        f_vals = [
            fact_id,
            field,
            json_value(value),
            event.headline if field != "document_text" else parsed.text[:1000],
            event.evidence_pages[0] if event.evidence_pages else None,
            "manual-manifest",
            "1",
            1.0,
            "VALID",
        ]
        if "event_revision_id" in fact_cols:
            f_fields.insert(1, "event_revision_id")
            f_vals.insert(1, revision_id)
        if "event_id" in fact_cols:
            f_fields.insert(1, "event_id")
            f_vals.insert(1, event_id)
        connection.execute(
            f"INSERT INTO extracted_fact({','.join(f_fields)}) VALUES({','.join('?' for _ in f_fields)})",
            f_vals,
        )
    return event_id, True

