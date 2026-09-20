from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from qual_event_engine.decisions.risk import apply_negative_overlay, entry_gate
from qual_event_engine.domain.models import StrategyConfig
from qual_event_engine.events.ratings import verified_upgrade
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.operations.hashing import sha256_json
from qual_event_engine.persistence.repositories import utc_now


def applicable_strategies(event: sqlite3.Row, strategies: dict[str, StrategyConfig]) -> list[str]:
    return [
        strategy_id
        for strategy_id, config in strategies.items()
        if config.enabled
        and event["event_type"] in config.event_types
        and int(event["firmness_level"]) >= config.minimum_firmness_level
    ]


def process_unassessed_events(
    connection: sqlite3.Connection,
    analyst: Analyst,
    strategies: dict[str, StrategyConfig],
) -> int:
    rows = connection.execute(
        """SELECT event_id, observation_id, isin, symbol, legal_name, sector, event_type, event_status,
                  firmness_level, event_value_inr, ttm_revenue_inr, materiality_ratio,
                  entity_match_status, headline, event_state
           FROM canonical_event
           WHERE event_state='INGESTED'"""
    ).fetchall()
    processed = 0
    for row in rows:
        event = dict(row)
        if event["event_type"] == "NEGATIVE_GOVERNANCE":
            apply_negative_overlay(connection, event["event_id"], event["symbol"], sessions=20)
            connection.execute(
                "UPDATE canonical_event SET event_state='NEGATIVE_OVERLAY_APPLIED' WHERE event_id=?",
                (event["event_id"],),
            )
            processed += 1
            continue

        # 1. Retrieve raw document text
        doc_row = connection.execute(
            """SELECT ef.value_json, rd.local_path
               FROM canonical_event ce
               LEFT JOIN source_observation so ON ce.observation_id = so.observation_id
               LEFT JOIN raw_document rd ON so.raw_sha256 = rd.raw_sha256
               LEFT JOIN extracted_fact ef ON ef.event_id = ce.event_id AND ef.field_name = 'document_text'
               WHERE ce.event_id = ?""",
            (event["event_id"],),
        ).fetchone()
        raw_document_text = ""
        if doc_row:
            if doc_row["value_json"]:
                try:
                    loaded = json.loads(doc_row["value_json"])
                    raw_document_text = loaded if isinstance(loaded, str) else str(loaded)
                except (json.JSONDecodeError, ValueError):
                    raw_document_text = str(doc_row["value_json"])
            elif doc_row["local_path"]:
                try:
                    p = Path(doc_row["local_path"])
                    if p.exists():
                        raw_document_text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    raw_document_text = ""
        if not raw_document_text:
            ev_row = connection.execute(
                "SELECT evidence_text FROM extracted_fact WHERE event_id=? AND field_name='document_text'",
                (event["event_id"],),
            ).fetchone()
            if ev_row and ev_row["evidence_text"]:
                raw_document_text = str(ev_row["evidence_text"])
            else:
                raw_document_text = event["headline"]

        # Structured context for Stage 1
        existing_facts = connection.execute(
            "SELECT field_name, value_json FROM extracted_fact WHERE event_id=?",
            (event["event_id"],),
        ).fetchall()
        structured_context: dict[str, Any] = {
            "symbol": event["symbol"],
            "event_type": event["event_type"],
            "headline": event["headline"],
        }
        if event.get("event_value_inr") is not None:
            structured_context["event_value_inr"] = event["event_value_inr"]
        if event.get("ttm_revenue_inr") is not None:
            structured_context["ttm_revenue_inr"] = event["ttm_revenue_inr"]
        for f in existing_facts:
            fn = f["field_name"]
            if fn not in structured_context and fn != "document_text":
                try:
                    structured_context[fn] = json.loads(f["value_json"])
                except (json.JSONDecodeError, ValueError):
                    structured_context[fn] = f["value_json"]

        if raw_document_text and "document_excerpt" not in structured_context:
            structured_context["document_excerpt"] = raw_document_text.strip()[:200]

        # Stage 1: Extract facts from raw document
        extraction_result = analyst.extract_facts(raw_document_text, structured_context)

        # Deterministic verbatim grounding validation check
        ungrounded_facts = [f for f in extraction_result.facts if f.validation_status == "UNGROUNDED"]
        grounding_failed = bool(ungrounded_facts) or len(extraction_result.facts) == 0

        # Persist extracted facts to database
        for fact in extraction_result.facts:
            connection.execute(
                """INSERT INTO extracted_fact(
                  fact_id,event_id,field_name,value_json,evidence_text,page_number,
                  extractor_name,extractor_version,confidence,validation_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id, field_name) DO UPDATE SET
                  value_json=excluded.value_json,
                  evidence_text=excluded.evidence_text,
                  confidence=excluded.confidence,
                  validation_status=excluded.validation_status""",
                (
                    str(uuid4()),
                    event["event_id"],
                    fact.field_name,
                    json.dumps(fact.value, default=str),
                    fact.evidence_text,
                    fact.page_number,
                    "analyst-stage1",
                    "1",
                    fact.confidence,
                    fact.validation_status,
                ),
            )

        if grounding_failed:
            connection.execute(
                """INSERT OR REPLACE INTO extracted_fact(
                  fact_id,event_id,field_name,value_json,evidence_text,page_number,
                  extractor_name,extractor_version,confidence,validation_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    event["event_id"],
                    "grounding_validation",
                    json.dumps({"allowed": False, "reason": "Stage 1 grounding validation failed"}),
                    "Verbatim grounding validation failed: ungrounded or missing facts",
                    None,
                    "grounding-validator",
                    "1",
                    0.0,
                    "BLOCKED",
                ),
            )
            connection.execute(
                "UPDATE canonical_event SET event_state='BLOCKED' WHERE event_id=?",
                (event["event_id"],),
            )
            processed += 1
            continue

        # Validated facts passed to Stage 2: assess()
        validated_facts = [f for f in extraction_result.facts if f.validation_status == "VERIFIED"]
        result = analyst.assess(event, validated_facts)
        assessment = result.assessment
        rating_is_valid = True
        if event["event_type"] == "CREDIT_UPGRADE":
            facts = connection.execute(
                "SELECT field_name,value_json FROM extracted_fact WHERE event_id=?",
                (event["event_id"],),
            ).fetchall()
            values = {fact["field_name"]: fact["value_json"] for fact in facts}
            previous = values.get("previous_rating")
            new = values.get("new_rating")
            rating_is_valid = verified_upgrade(
                previous.strip('"') if previous else None,
                new.strip('"') if new else None,
            )
        semantic_valid = assessment.recommendation != "BUY_CANDIDATE" or (
            event["entity_match_status"] == "VERIFIED"
            and int(event["firmness_level"]) >= 4
            and rating_is_valid
        )
        connection.execute(
            """INSERT INTO analyst_assessment(
                 assessment_id,event_id,model_id,model_version,prompt_version,input_hash,output_hash,
                 recommendation,rationale,invalidating_fact,confidence,schema_valid,semantic_valid,
                 latency_ms,created_at_utc
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(event_id) DO UPDATE SET
                 model_id=excluded.model_id,
                 model_version=excluded.model_version,
                 prompt_version=excluded.prompt_version,
                 input_hash=excluded.input_hash,
                 output_hash=excluded.output_hash,
                 recommendation=excluded.recommendation,
                 rationale=excluded.rationale,
                 invalidating_fact=excluded.invalidating_fact,
                 confidence=excluded.confidence,
                 schema_valid=excluded.schema_valid,
                 semantic_valid=excluded.semantic_valid,
                 latency_ms=excluded.latency_ms,
                 created_at_utc=excluded.created_at_utc""",
            (
                str(uuid4()),
                event["event_id"],
                assessment.model_id,
                assessment.model_id,
                assessment.prompt_version,
                result.input_hash,
                result.output_hash,
                assessment.recommendation,
                assessment.rationale,
                assessment.invalidating_fact,
                assessment.confidence,
                1,
                int(semantic_valid),
                result.latency_ms,
                utc_now(),
            ),
        )
        gate_passed, gate_reason = entry_gate(connection, row)
        state = (
            "REVIEW_PENDING"
            if (
                semantic_valid
                and assessment.recommendation == "BUY_CANDIDATE"
                and applicable_strategies(row, strategies)
                and gate_passed
            )
            else "BLOCKED"
        )
        connection.execute(
            "UPDATE canonical_event SET event_state=? WHERE event_id=?",
            (state, event["event_id"]),
        )
        if not gate_passed:
            connection.execute(
                """INSERT OR REPLACE INTO extracted_fact(
                  fact_id,event_id,field_name,value_json,evidence_text,page_number,
                  extractor_name,extractor_version,confidence,validation_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    event["event_id"],
                    "risk_gate",
                    json.dumps({"allowed": False, "reason": gate_reason}),
                    gate_reason,
                    None,
                    "risk-engine",
                    "1",
                    1.0,
                    "BLOCKED",
                ),
            )
        processed += 1
    return processed


def record_review(
    connection: sqlite3.Connection,
    event_id: str,
    reviewer: str,
    decision: str,
    rationale: str,
) -> str:
    event = connection.execute(
        "SELECT event_state FROM canonical_event WHERE event_id=?", (event_id,)
    ).fetchone()
    if not event:
        raise ValueError("Event not found")
    if event["event_state"] != "REVIEW_PENDING":
        raise ValueError("Only REVIEW_PENDING events can be reviewed")
    if decision not in {"APPROVE", "REJECT", "REQUEST_MORE_EVIDENCE", "OVERRIDE_TO_WATCH"}:
        raise ValueError("Invalid review decision")
    review_id = str(uuid4())
    connection.execute(
        """INSERT INTO review_decision(review_id,event_id,reviewer,decision,rationale,reviewed_at_utc)
           VALUES(?,?,?,?,?,?)""",
        (review_id, event_id, reviewer, decision, rationale, utc_now()),
    )
    state = "APPROVED" if decision == "APPROVE" else "BLOCKED"
    connection.execute(
        "UPDATE canonical_event SET event_state=? WHERE event_id=?", (state, event_id)
    )
    return review_id


def create_paper_intents(
    connection: sqlite3.Connection,
    strategies: dict[str, StrategyConfig],
    paper_nav_inr: float,
) -> int:
    incident = connection.execute("SELECT 1 FROM incident WHERE status='OPEN' LIMIT 1").fetchone()
    if incident:
        return 0
    rows = connection.execute(
        """SELECT event_id,isin,symbol,event_type,firmness_level,headline
           FROM canonical_event WHERE event_state='APPROVED'"""
    ).fetchall()
    created = 0
    now = datetime.now(UTC)
    for event in rows:
        for strategy_id in applicable_strategies(event, strategies):
            config = strategies[strategy_id]
            duplicate = connection.execute(
                "SELECT 1 FROM paper_order WHERE event_id=? AND strategy_id=?",
                (event["event_id"], strategy_id),
            ).fetchone()
            if duplicate:
                continue
            connection.execute(
                """INSERT INTO paper_order(
                  paper_order_id,client_order_id,event_id,strategy_id,strategy_version,symbol,isin,side,
                  quantity_requested,quantity_remaining,order_type,limit_price,trigger_price,
                  participation_cap_pct,valid_from_utc,valid_until_utc,status,decision_snapshot_hash,created_at_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    f"{event['event_id']}:{strategy_id}:BUY",
                    event["event_id"],
                    strategy_id,
                    "1",
                    event["symbol"],
                    event["isin"],
                    "BUY",
                    1,
                    1,
                    "PAPER_MARKET",
                    None,
                    None,
                    config.maximum_participation_pct,
                    now.isoformat(),
                    (now + timedelta(days=1)).isoformat(),
                    "PENDING_PRICE",
                    sha256_json(
                        {"event": event["event_id"], "strategy": strategy_id, "nav": paper_nav_inr}
                    ),
                    now.isoformat(),
                ),
            )
            created += 1
        connection.execute(
            "UPDATE canonical_event SET event_state='PAPER_ORDER_SENT' WHERE event_id=?",
            (event["event_id"],),
        )
    return created
