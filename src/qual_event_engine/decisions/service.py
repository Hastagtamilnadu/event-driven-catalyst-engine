from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from qual_event_engine.decisions.risk import apply_negative_overlay, entry_gate
from qual_event_engine.domain.enums import CredibilityFlag
from qual_event_engine.domain.models import StrategyConfig
from qual_event_engine.events.ratings import verified_upgrade
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.intelligence.dossier import DossierBuilder
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
    as_of: str | None = None,
) -> int:
    query = """SELECT event_id, observation_id, isin, symbol, legal_name, sector, event_type, event_status,
                  firmness_level, event_value_inr, ttm_revenue_inr, materiality_ratio,
                  entity_match_status, headline, event_state
           FROM canonical_event
           WHERE event_state='INGESTED'"""
    params: list[object] = []
    if as_of:
        query += " AND created_at_utc <= ?"
        params.append(as_of)
    rows = connection.execute(query, params).fetchall()
    print(f"\n[Engine] Found {len(rows)} unassessed event(s) to process.", flush=True)
    processed = 0
    for idx, row in enumerate(rows, 1):
        event = dict(row)
        print(f"\n---> [{idx}/{len(rows)}] Event {event['event_id'][:8]}... | Symbol: {event['symbol']} | Type: {event['event_type']} | Firmness: {event['firmness_level']}", flush=True)
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
        print("    [Stage 1] Extracting facts from document with AI...", flush=True)
        extraction_result = analyst.extract_facts(raw_document_text, structured_context)

        # Deterministic verbatim grounding validation check
        verified_facts = [f for f in extraction_result.facts if f.validation_status == "VERIFIED"]
        grounding_failed = len(verified_facts) == 0
        print(f"    [Stage 1] Extracted {len(extraction_result.facts)} facts ({len(verified_facts)} verified, Grounding failed: {grounding_failed})", flush=True)

        # Ensure event_revision exists for this event
        rev_row = connection.execute(
            "SELECT event_revision_id FROM event_revision WHERE event_id=? ORDER BY revision_number DESC LIMIT 1",
            (event["event_id"],),
        ).fetchone()
        if rev_row:
            event_rev_id = str(rev_row[0])
        else:
            event_rev_id = str(uuid4())
            obs_id = event.get("observation_id") or "obs-unknown"
            r_cols = {str(r[0]) for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("event_revision",)).fetchall()}
            if r_cols:
                r_f = ["event_id", "observation_id", "revision_number", "revision_kind", "material_change_flag"]
                r_v = [event["event_id"], obs_id, 1, "ORIGINAL", 0]
                if "event_revision_id" in r_cols:
                    r_f.insert(0, "event_revision_id")
                    r_v.insert(0, event_rev_id)
                if "revision_id" in r_cols and "revision_id" not in r_f:
                    r_f.insert(0, "revision_id")
                    r_v.insert(0, event_rev_id)
                if "new_value_json" in r_cols:
                    r_f.append("new_value_json")
                    r_v.append("{}")
                if "reason" in r_cols:
                    r_f.append("reason")
                    r_v.append("INITIAL")
                if "revised_by" in r_cols:
                    r_f.append("revised_by")
                    r_v.append("SYSTEM")
                if "revised_at_utc" in r_cols:
                    r_f.append("revised_at_utc")
                    r_v.append(utc_now())
                if "revised_field" in r_cols:
                    r_f.append("revised_field")
                    r_v.append("INITIAL")
                connection.execute(
                    f"INSERT OR IGNORE INTO event_revision({','.join(r_f)}) VALUES({','.join('?' for _ in r_f)})",
                    r_v,
                )

        fact_cols = {str(r[0]) for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("extracted_fact",)).fetchall()}
        # Persist extracted facts to database
        for fact in extraction_result.facts:
            f_cols_list = ["fact_id", "field_name", "value_json", "evidence_text", "page_number", "extractor_name", "extractor_version", "confidence", "validation_status"]
            f_vals_list = [
                str(uuid4()),
                fact.field_name,
                json.dumps(fact.value, default=str),
                fact.evidence_text,
                fact.page_number,
                "analyst-stage1",
                "1",
                fact.confidence,
                fact.validation_status,
            ]
            if "event_revision_id" in fact_cols:
                f_cols_list.insert(1, "event_revision_id")
                f_vals_list.insert(1, event_rev_id)
            if "event_id" in fact_cols:
                f_cols_list.insert(1, "event_id")
                f_vals_list.insert(1, event["event_id"])
            connection.execute(
                f"""INSERT INTO extracted_fact({','.join(f_cols_list)}) VALUES({','.join('?' for _ in f_cols_list)})
                ON CONFLICT(event_id, field_name) DO UPDATE SET
                  value_json=excluded.value_json,
                  evidence_text=excluded.evidence_text,
                  confidence=excluded.confidence,
                  validation_status=excluded.validation_status""",
                f_vals_list,
            )

        if grounding_failed:
            gf_cols = ["fact_id", "field_name", "value_json", "evidence_text", "page_number", "extractor_name", "extractor_version", "confidence", "validation_status"]
            gf_vals = [
                str(uuid4()),
                "grounding_validation",
                json.dumps({"allowed": False, "reason": "Stage 1 grounding validation failed"}),
                "Verbatim grounding validation failed: ungrounded or missing facts",
                None,
                "grounding-validator",
                "1",
                0.0,
                "BLOCKED",
            ]
            if "event_revision_id" in fact_cols:
                gf_cols.insert(1, "event_revision_id")
                gf_vals.insert(1, event_rev_id)
            if "event_id" in fact_cols:
                gf_cols.insert(1, "event_id")
                gf_vals.insert(1, event["event_id"])
            connection.execute(
                f"""INSERT OR REPLACE INTO extracted_fact({','.join(gf_cols)}) VALUES({','.join('?' for _ in gf_cols)})""",
                gf_vals,
            )
            connection.execute(
                "UPDATE canonical_event SET event_state='BLOCKED' WHERE event_id=?",
                (event["event_id"],),
            )
            processed += 1
            continue

        # Validated facts passed to Stage 2: assess()
        validated_facts = [f for f in extraction_result.facts if f.validation_status == "VERIFIED"]
        now_dt = datetime.now(UTC)
        dossier_builder = DossierBuilder(connection)
        dossier = dossier_builder.build_dossier(event["symbol"], now_dt)
        dossier_dict: dict[str, Any] = {
            "symbol": dossier.symbol,
            "legal_name": dossier.legal_name,
            "sector": dossier.sector,
            "market_cap_inr": dossier.market_cap_inr,
            "adv20": dossier.adv20,
            "adt20": dossier.adt20,
            "surveillance_status": dossier.surveillance_status,
            "credibility_flags": [
                {"flag": f.flag.value, "triggered": f.triggered, "action": f.default_action}
                for f in dossier.credibility_flags
            ],
            "valuation_profile": {
                "trailing_pe": dossier.valuation_profile.trailing_pe if dossier.valuation_profile else None,
                "sector_median_pe": dossier.valuation_profile.sector_median_pe if dossier.valuation_profile else None,
                "pb_ratio": dossier.valuation_profile.pb_ratio if dossier.valuation_profile else None,
                "ev_ebitda": dossier.valuation_profile.ev_ebitda if dossier.valuation_profile else None,
                "net_debt_to_ebitda": dossier.valuation_profile.net_debt_to_ebitda if dossier.valuation_profile else None,
                "interest_coverage": dossier.valuation_profile.interest_coverage if dossier.valuation_profile else None,
                "cash_conversion_cycle_days": dossier.valuation_profile.cash_conversion_cycle_days if dossier.valuation_profile else None,
            } if dossier.valuation_profile else {},
        }

        print("    [Stage 2] Generating equity research assessment with AI...", flush=True)
        result = analyst.assess(event, validated_facts, point_in_time_dossier=dossier_dict)
        assessment = result.assessment
        print(f"    [Stage 2] Assessment: {assessment.recommendation} (Confidence: {assessment.confidence})", flush=True)
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

        # §11.3 & §32.3 Valuation Hurdle & Cash Flow Purity Policy:
        val_stretch_triggered = any(
            f.flag == CredibilityFlag.VALUATION_STRETCH_RISK and f.triggered
            for f in dossier.credibility_flags
        )
        debt_refinance_triggered = any(
            f.flag == CredibilityFlag.DEBT_REFINANCING_RISK and f.triggered
            for f in dossier.credibility_flags
        )
        materiality = float(event.get("materiality_ratio") or 0.0)
        valuation_hurdle_passed = True
        if val_stretch_triggered and materiality < 0.50 and assessment.recommendation == "BUY_CANDIDATE":
            print(f"    [Valuation Hurdle] Overriding BUY_CANDIDATE to WATCH: VALUATION_STRETCH_RISK (Materiality {materiality:.2%} < 50%)", flush=True)
            valuation_hurdle_passed = False
        if debt_refinance_triggered and assessment.recommendation == "BUY_CANDIDATE":
            print("    [Cash Flow Purity] Overriding BUY_CANDIDATE to WATCH: DEBT_REFINANCING_RISK detected", flush=True)
            valuation_hurdle_passed = False

        semantic_valid = assessment.recommendation != "BUY_CANDIDATE" or (
            event["entity_match_status"] == "VERIFIED"
            and int(event["firmness_level"]) >= 4
            and rating_is_valid
            and valuation_hurdle_passed
        )
        assess_cols = {str(r[0]) for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("analyst_assessment",)).fetchall()}
        a_cols = [
            "assessment_id", "model_id", "model_version", "prompt_version", "input_hash", "output_hash",
            "recommendation", "rationale", "invalidating_fact", "confidence", "schema_valid", "semantic_valid",
            "latency_ms", "created_at_utc"
        ]
        a_vals = [
            str(uuid4()),
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
        ]
        if "event_id" in assess_cols:
            a_cols.insert(1, "event_id")
            a_vals.insert(1, event["event_id"])
        if "event_revision_id" in assess_cols:
            a_cols.insert(1, "event_revision_id")
            a_vals.insert(1, event_rev_id)
        if "dossier_hash" in assess_cols:
            a_cols.insert(2, "dossier_hash")
            a_vals.insert(2, "")
        connection.execute(
            f"""INSERT INTO analyst_assessment({','.join(a_cols)}) VALUES({','.join('?' for _ in a_cols)})
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
            a_vals,
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
        print(f"    [Result] Event state transitioned -> {state}", flush=True)
        if not gate_passed:
            rf_cols = ["fact_id", "field_name", "value_json", "evidence_text", "page_number", "extractor_name", "extractor_version", "confidence", "validation_status"]
            rf_vals = [
                str(uuid4()),
                "risk_gate",
                json.dumps({"allowed": False, "reason": gate_reason}),
                gate_reason,
                None,
                "risk-engine",
                "1",
                1.0,
                "BLOCKED",
            ]
            if "event_revision_id" in fact_cols:
                rf_cols.insert(1, "event_revision_id")
                rf_vals.insert(1, event_rev_id)
            if "event_id" in fact_cols:
                rf_cols.insert(1, "event_id")
                rf_vals.insert(1, event["event_id"])
            connection.execute(
                f"""INSERT OR REPLACE INTO extracted_fact({','.join(rf_cols)}) VALUES({','.join('?' for _ in rf_cols)})""",
                rf_vals,
            )
        connection.commit()
        processed += 1
    return processed


def record_review(
    connection: sqlite3.Connection,
    event_id: str,
    reviewer: str,
    decision: str,
    rationale: str,
    version: str | None = None,
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
    prior = connection.execute(
        "SELECT decision, rationale FROM review_decision WHERE event_id=? ORDER BY reviewed_at_utc DESC",
        (event_id,),
    ).fetchall()
    if version:
        marker = "[review_version=" + version + "]"
        if any(marker in str(row["rationale"] or "") for row in prior):
            raise ValueError("Stale review submission")
    terminal_prior = any(str(row["decision"]) in {"APPROVE", "REJECT", "OVERRIDE_TO_WATCH"} for row in prior)
    if terminal_prior:
        raise ValueError("Duplicate review submission")
    review_id = str(uuid4())
    rationale_stored = rationale if version is None else f"{rationale}\n[review_version={version}]"
    cols = {
        str(r[0])
        for r in connection.execute("SELECT name FROM pragma_table_info(?)", ("review_decision",)).fetchall()
    }
    assessment_id = None
    if "assessment_id" in cols:
        try:
            assessment_row = connection.execute(
                """
                SELECT a.assessment_id
                FROM analyst_assessment a
                JOIN event_revision r ON r.event_revision_id = a.event_revision_id
                WHERE r.event_id=?
                ORDER BY a.created_at_utc DESC
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            assessment_row = None
        assessment_id = assessment_row[0] if assessment_row else None
    insert_cols = ["review_id", "event_id", "reviewer", "decision", "rationale", "reviewed_at_utc"]
    values: list[object] = [review_id, event_id, reviewer, decision, rationale_stored, utc_now()]
    if "assessment_id" in cols:
        insert_cols.insert(2, "assessment_id")
        values.insert(2, assessment_id)
    placeholders = ",".join("?" for _ in insert_cols)
    connection.execute(
        "INSERT INTO review_decision(" + ",".join(insert_cols) + ") VALUES(" + placeholders + ")",
        values,
    )
    if decision == "APPROVE":
        state = "APPROVED_PAPER_INTENT"
    elif decision == "REQUEST_MORE_EVIDENCE":
        state = "REVIEW_PENDING"
    else:
        state = "REJECTED"
    connection.execute(
        "UPDATE canonical_event SET event_state=? WHERE event_id=?", (state, event_id)
    )
    return review_id


def _frozen_strategy_ids(connection: sqlite3.Connection) -> tuple[bool, set[str]]:
    """§16.2 / §20.2: global freeze vs source-outage strategy-only freeze."""
    rows = connection.execute(
        "SELECT service, summary FROM incident WHERE status='OPEN'"
    ).fetchall()
    if not rows:
        return False, set()
    strategy_only: set[str] = set()
    global_freeze = False
    for row in rows:
        service = str(row["service"] or "")
        summary = str(row["summary"] or "")
        if service == "SOURCE_OUTAGE" or service.startswith("SOURCE_OUTAGE"):
            marker = "affected_strategy_id="
            if marker in summary:
                strategy_only.add(summary.split(marker, 1)[1].split()[0].strip())
            else:
                global_freeze = True
        else:
            global_freeze = True
    return global_freeze, strategy_only


def create_paper_intents(
    connection: sqlite3.Connection,
    strategies: dict[str, StrategyConfig],
    paper_nav_inr: float,
) -> int:
    freeze_all, frozen_strategies = _frozen_strategy_ids(connection)
    if freeze_all:
        return 0
    rows = connection.execute(
        """SELECT event_id,isin,symbol,event_type,firmness_level,headline
           FROM canonical_event WHERE event_state IN ('APPROVED_PAPER_INTENT','APPROVED')"""
    ).fetchall()
    created = 0
    now = datetime.now(UTC)
    order_cols = {
        str(r[0])
        for r in connection.execute(
            "SELECT name FROM pragma_table_info(?)", ("paper_order",)
        ).fetchall()
    }
    for event in rows:
        for strategy_id in applicable_strategies(event, strategies):
            if strategy_id in frozen_strategies:
                continue
            config = strategies[strategy_id]
            duplicate = connection.execute(
                "SELECT 1 FROM paper_order WHERE event_id=? AND strategy_id=?",
                (event["event_id"], strategy_id),
            ).fetchone()
            if duplicate:
                continue
            participation = float(config.maximum_participation_pct)
            if participation > 1.0:
                participation = participation / 100.0
            elif participation == 1.0:
                participation = 0.01
            insert_cols = [
                "paper_order_id",
                "client_order_id",
                "event_id",
                "strategy_id",
                "strategy_version",
                "symbol",
                "isin",
                "side",
                "quantity_requested",
                "order_type",
                "limit_price",
                "trigger_price",
                "participation_cap",
                "valid_from_utc",
                "valid_until_utc",
                "status",
                "decision_snapshot_hash",
                "created_at_utc",
            ]
            values: list[object] = [
                str(uuid4()),
                f"{event['event_id']}:{strategy_id}:BUY",
                event["event_id"],
                strategy_id,
                "1",
                event["symbol"],
                event["isin"],
                "BUY",
                1,
                "PAPER_MARKET",
                None,
                None,
                participation,
                now.isoformat(),
                (now + timedelta(days=1)).isoformat(),
                "PENDING_PRICE",
                sha256_json(
                    {"event": event["event_id"], "strategy": strategy_id, "nav": paper_nav_inr}
                ),
                now.isoformat(),
            ]
            if "quantity_remaining" in order_cols:
                insert_cols.insert(9, "quantity_remaining")
                values.insert(9, 1)
            if "participation_cap_pct" in order_cols and "participation_cap_pct" not in insert_cols:
                insert_cols.append("participation_cap_pct")
                values.append(participation * 100.0 if participation < 1.0 else participation)
            placeholders = ",".join("?" for _ in insert_cols)
            connection.execute(
                "INSERT INTO paper_order(" + ",".join(insert_cols) + ") VALUES(" + placeholders + ")",
                values,
            )
            created += 1
        has_order = connection.execute(
            "SELECT 1 FROM paper_order WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()
        if has_order:
            connection.execute(
                "UPDATE canonical_event SET event_state='PAPER_ORDER_SENT' WHERE event_id=?",
                (event["event_id"],),
            )
    return created
