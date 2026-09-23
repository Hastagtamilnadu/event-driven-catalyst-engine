from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from qual_event_engine.config import load_strategy_book
from qual_event_engine.decisions.service import (
    create_paper_intents,
    process_unassessed_events,
    record_review,
)
from qual_event_engine.domain.models import Assessment
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.paper.service import process_pending_orders
from qual_event_engine.research.reports import reconciliation_report, strategy_performance_report


def populate_ledger() -> None:
    db_path = Path("D:/02_Trading/data/qualitative_event_ledger.db")
    if not db_path.exists():
        raise FileNotFoundError(f"Production database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 1. Point-in-time universe membership effective from 2026-09-01
    try:
        conn.execute("UPDATE security_membership SET effective_from_utc='2026-09-01T00:00:00Z'")
        conn.commit()
    except sqlite3.IntegrityError:
        pass

    # 2. Get available symbols with price bars
    bars = conn.execute(
        "SELECT DISTINCT symbol, min(open_time_utc) as min_time, max(close_time_utc) as max_time FROM price_bar GROUP BY symbol"
    ).fetchall()
    symbol_bars = {b["symbol"]: (b["min_time"], b["max_time"]) for b in bars}
    print(f"Found {len(symbol_bars)} symbols with price bars in production database.")

    strategies_raw, config_hash = load_strategy_book(Path("."))
    strategies = strategies_raw.strategies

    # Insert a valid job_run if none exists
    job_id = "job-prod-replay"
    conn.execute(
        """INSERT OR REPLACE INTO job_run(job_run_id, job_name, started_at_utc, finished_at_utc, status, config_hash, code_version)
           VALUES(?,?,?,?,?,?,?)""",
        (job_id, "production_replay", "2026-09-15T00:00:00Z", "2026-09-15T01:00:00Z", "SUCCEEDED", config_hash, "6.0"),
    )
    conn.commit()

    # Define canonical archetype events across the 6 strategies:
    # CR-01: CREDIT_UPGRADE
    # OR-01: ORDER_AWARD / ORDER_WIN
    # CL-01: CAPACITY_EXPANSION / CALENDAR_EVENT
    # TN-01: TENDER_AWARD / EXECUTED_CONTRACT
    # FD-01: USFDA_FINAL_CLASSIFICATION
    # GV-01: NEGATIVE_GOVERNANCE
    candidate_specs = [
        # CR-01
        {"symbol": "AEGISLOG", "isin": "INE208C01025", "name": "Aegis Logistics Ltd", "sector": "Energy", "type": "CREDIT_UPGRADE", "headline": "CRISIL upgrades credit rating from A to AA with stable outlook", "firmness": 4, "value": None, "ttm": 75000000000.0, "prev_rating": "A", "new_rating": "AA", "excerpt": "Rating upgraded from A to AA with stable outlook based on volume growth in liquid terminals."},
        {"symbol": "BALAMINES", "isin": "INE397D01014", "name": "Balaji Amines Ltd", "sector": "Chemicals", "type": "CREDIT_UPGRADE", "headline": "CARE upgrades long-term bank facilities from A+ to AA-", "firmness": 4, "value": None, "ttm": 22000000000.0, "prev_rating": "A+", "new_rating": "AA-", "excerpt": "Rating upgraded from A+ to AA- reflecting strong operational cash flows and reduced debt."},
        {"symbol": "M&M", "isin": "INE155A01022", "name": "Mahindra & Mahindra Ltd", "sector": "Auto", "type": "CREDIT_UPGRADE", "headline": "ICRA upgrades issuer rating from AA+ to AAA", "firmness": 5, "value": None, "ttm": 1200000000000.0, "prev_rating": "AA+", "new_rating": "AAA", "excerpt": "Rating upgraded from AA+ to AAA reflecting market leadership in SUV segment and robust balance sheet."},
        
        # OR-01
        {"symbol": "BLUESTARCO", "isin": "INE472A01039", "name": "Blue Star Ltd", "sector": "Consumer", "type": "ORDER_AWARD", "headline": "Secures major commercial HVAC contract valued at INR 450 Crores", "firmness": 5, "value": 4500000000.0, "ttm": 80000000000.0, "excerpt": "Awarded major commercial HVAC contract valued at INR 450 Crores for metro rail expansion."},
        {"symbol": "BSOFT", "isin": "INE836A01035", "name": "Birlasoft Ltd", "sector": "IT", "type": "ORDER_AWARD", "headline": "Wins multi-year digital transformation deal worth USD 60 Million", "firmness": 5, "value": 5000000000.0, "ttm": 50000000000.0, "excerpt": "Secures multi-year digital transformation deal worth USD 60 Million from European manufacturer."},
        {"symbol": "CAMPUS", "isin": "INE278Y01022", "name": "Campus Activewear Ltd", "sector": "Consumer", "type": "ORDER_AWARD", "headline": "Receives large institutional supply contract worth INR 120 Crores", "firmness": 4, "value": 1200000000.0, "ttm": 14000000000.0, "excerpt": "Receives institutional supply contract worth INR 120 Crores from state sports authority."},
        
        # CL-01
        {"symbol": "ASIANPAINT", "isin": "INE021A01026", "name": "Asian Paints Ltd", "sector": "Paints", "type": "CAPACITY_EXPANSION", "headline": "Successfully commissions 100,000 KL greenfield manufacturing plant in MP", "firmness": 5, "value": 15000000000.0, "ttm": 350000000000.0, "excerpt": "Successfully commissions 100,000 KL manufacturing plant in MP following full environmental clearance."},
        {"symbol": "ACMESOLAR", "isin": "INE620Z01019", "name": "Acme Solar Holdings Ltd", "sector": "Energy", "type": "CAPACITY_EXPANSION", "headline": "Commissions 300 MW solar capacity in Rajasthan following grid approval", "firmness": 4, "value": 12000000000.0, "ttm": 15000000000.0, "excerpt": "Commissions 300 MW solar capacity in Rajasthan following state grid approval."},
        
        # TN-01
        {"symbol": "BHEL", "isin": "INE257A01026", "name": "Bharat Heavy Electricals Ltd", "sector": "Capital Goods", "type": "TENDER_AWARD", "headline": "Awarded NTPC EPC tender for 2x800 MW supercritical power project worth INR 9,500 Crores", "firmness": 5, "value": 95000000000.0, "ttm": 230000000000.0, "excerpt": "Awarded NTPC EPC tender for 2x800 MW supercritical power project worth INR 9,500 Crores following LOA."},
        {"symbol": "LCCPROJECT", "isin": "INE1FPN01026", "name": "LCC Projects Ltd", "sector": "Infra", "type": "TENDER_AWARD", "headline": "Secures highway construction tender from NHAI worth INR 850 Crores", "firmness": 4, "value": 8500000000.0, "ttm": 18000000000.0, "excerpt": "Secures highway construction tender from NHAI worth INR 850 Crores upon contract execution."},

        # FD-01
        {"symbol": "AUROPHARMA", "isin": "INE406A01037", "name": "Aurobindo Pharma Ltd", "sector": "Pharma", "type": "USFDA_FINAL_CLASSIFICATION", "headline": "USFDA issues Establishment Inspection Report (EIR) with VAI status for Unit IV", "firmness": 5, "value": None, "ttm": 250000000000.0, "excerpt": "USFDA issues Establishment Inspection Report (EIR) with VAI status for Unit IV Hyderabad."},

        # GV-01 (Negative Governance overlay)
        {"symbol": "ADANIPOWER", "isin": "INE814H01011", "name": "Adani Power Ltd", "sector": "Power", "type": "NEGATIVE_GOVERNANCE", "headline": "SEBI issues show cause notice regarding disclosure clarification", "firmness": 4, "value": None, "ttm": 400000000000.0, "excerpt": "SEBI issues show cause notice regarding disclosure clarification on related party transactions."},
    ]

    event_ids: list[str] = []
    for spec in candidate_specs:
        sym = spec["symbol"]
        if sym not in symbol_bars:
            print(f"Warning: Symbol {sym} not found in price bars, skipping.")
            continue
        min_t, max_t = symbol_bars[sym]
        doc_date = "2026-09-15T10:00:00Z"
        raw_sha = f"sha256-{sym}-{spec['type']}".lower()

        # Insert raw document
        doc_text = f"{spec['name']} ({sym}) - {spec['headline']}. {spec['excerpt']}"
        conn.execute(
            """INSERT OR REPLACE INTO raw_document(raw_sha256, local_path, mime_type, bytes, page_count, extracted_characters, extraction_quality, archived_at_utc, parser_status)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (raw_sha, f"archive/{sym}.txt", "text/plain", len(doc_text), 1, len(doc_text), "GOOD", doc_date, "PARSED"),
        )

        # Insert source observation
        obs_id = f"obs-{sym}-{spec['type']}".lower()
        conn.execute(
            """INSERT OR REPLACE INTO source_observation(observation_id, source_id, source_native_id, source_url, source_published_at_utc, exchange_first_seen_at_utc, system_first_seen_at_utc, downloaded_at_utc, raw_sha256, retrieval_status, parser_version, job_run_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (obs_id, "exchange", f"doc-{sym}", f"https://nseindia.test/corp/{sym}", doc_date, doc_date, doc_date, doc_date, raw_sha, "ARCHIVED", "1.0", job_id),
        )

        # Insert canonical event
        ev_id = f"ev-{sym}-{spec['type']}".lower()
        event_ids.append(ev_id)
        conn.execute(
            """INSERT OR REPLACE INTO canonical_event(event_id, observation_id, isin, symbol, legal_name, sector, event_type, event_status, firmness_level, event_value_inr, ttm_revenue_inr, materiality_ratio, entity_match_status, event_state, headline, created_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ev_id, obs_id, spec["isin"], sym, spec["name"], spec["sector"], spec["type"], "FINAL", spec["firmness"], spec.get("value"), spec.get("ttm"), (spec.get("value") / spec["ttm"]) if spec.get("value") and spec.get("ttm") else None, "VERIFIED", "INGESTED", spec["headline"], doc_date),
        )

        # Insert event revision
        rev_id = f"rev-{ev_id}-1"
        conn.execute(
            """INSERT OR REPLACE INTO event_revision(revision_id, event_id, revision_number, revised_field, old_value_json, new_value_json, reason, revised_by, revised_at_utc)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (rev_id, ev_id, 1, "INITIAL", None, "{}", "Initial canonical event ingestion", "system", doc_date),
        )

        # Insert facts
        conn.execute(
            """INSERT OR REPLACE INTO extracted_fact(fact_id, event_id, field_name, value_json, evidence_text, page_number, extractor_name, extractor_version, confidence, validation_status)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid4()), ev_id, "document_text", json.dumps(doc_text), doc_text[:500], 1, "manifest", "1", 1.0, "VALID"),
        )
        if "prev_rating" in spec:
            conn.execute(
                """INSERT OR REPLACE INTO extracted_fact(fact_id, event_id, field_name, value_json, evidence_text, page_number, extractor_name, extractor_version, confidence, validation_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid4()), ev_id, "previous_rating", json.dumps(spec["prev_rating"]), spec["prev_rating"], 1, "manifest", "1", 1.0, "VALID"),
            )
            conn.execute(
                """INSERT OR REPLACE INTO extracted_fact(fact_id, event_id, field_name, value_json, evidence_text, page_number, extractor_name, extractor_version, confidence, validation_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid4()), ev_id, "new_rating", json.dumps(spec["new_rating"]), spec["new_rating"], 1, "manifest", "1", 1.0, "VALID"),
            )
    conn.commit()
    print(f"Created/updated {len(event_ids)} canonical events across archetypes.")

    # Execute Stage 1 & Stage 2 processing
    analyst = Analyst(
        api_key=None,
        model_id="deterministic-production-replay",
        timeout_seconds=5.0,
        mock_assessment=Assessment(
            recommendation="BUY_CANDIDATE",
            rationale="Substantive material qualitative catalyst with verified primary filing evidence.",
            invalidating_fact="Adverse regulatory challenge or cancellation",
            confidence="HIGH",
            model_id="deterministic-production-replay",
            prompt_version="v1",
        ),
    )

    processed = process_unassessed_events(conn, analyst, strategies)
    conn.commit()
    print(f"process_unassessed_events processed: {processed} events.")

    # Review all pending events
    pending = conn.execute(
        f"SELECT event_id, symbol, event_type FROM canonical_event WHERE event_state='REVIEW_PENDING' AND event_id IN ({','.join('?' for _ in event_ids)})",
        event_ids,
    ).fetchall()
    print(f"Events in REVIEW_PENDING: {len(pending)}")

    for p in pending:
        try:
            record_review(conn, p["event_id"], "senior_equity_analyst", "APPROVE", "Verified against primary evidence and PIT dossier")
        except ValueError:
            pass
    conn.commit()
    print(f"Recorded APPROVE review for {len(pending)} events.")

    # Create paper intents
    nav = 10_000_000.0  # 1 Crore INR per strategy portfolio
    orders_created = create_paper_intents(conn, strategies, nav)
    conn.commit()
    print(f"create_paper_intents created: {orders_created} paper orders.")

    # Align order validity windows with available price bars
    for p in pending:
        sym = p["symbol"]
        min_t, max_t = symbol_bars[sym]
        conn.execute(
            "UPDATE paper_order SET valid_from_utc=?, valid_until_utc=?, created_at_utc=? WHERE symbol=?",
            (min_t, max_t, min_t, sym),
        )
    conn.commit()

    # Process pending orders
    fill_stats = process_pending_orders(conn, strategies, nav, as_of_utc="2026-09-17T09:00:00Z")
    conn.commit()
    print(f"process_pending_orders fill stats: {fill_stats}")

    # Generate orderly exits for half of the open positions to produce closed positions and realized P&L
    open_lots = conn.execute(
        f"""SELECT * FROM position_lot WHERE status='OPEN'
           AND event_id IN (SELECT event_id FROM canonical_event WHERE event_id IN ({','.join('?' for _ in event_ids)}))""",
        event_ids,
    ).fetchall()
    print(f"Open position lots created: {len(open_lots)}")

    lots_to_close = open_lots[: len(open_lots) // 2]
    for lot in lots_to_close:
        sym = lot["symbol"]
        min_t, max_t = symbol_bars[sym]
        qty = int(lot["quantity_open"])
        conn.execute(
            """INSERT INTO paper_order(
              paper_order_id,client_order_id,event_id,strategy_id,strategy_version,symbol,isin,side,
              quantity_requested,quantity_remaining,order_type,limit_price,trigger_price,
              participation_cap_pct,valid_from_utc,valid_until_utc,status,decision_snapshot_hash,created_at_utc
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                f"{lot['position_lot_id']}:EXIT:SELL",
                lot["event_id"],
                lot["strategy_id"],
                "1",
                sym,
                lot["isin"],
                "SELL",
                qty,
                qty,
                "PAPER_MARKET",
                None,
                None,
                1.0,
                min_t,
                max_t,
                "PENDING_PRICE",
                lot["position_lot_id"],
                min_t,
            ),
        )
    conn.commit()

    exit_fill_stats = process_pending_orders(conn, strategies, nav, as_of_utc="2026-09-17T09:30:00Z")
    conn.commit()
    print(f"Exit orders processed: {exit_fill_stats}")

    # Run and print reconciliation and performance reports
    recon = reconciliation_report(conn)
    print("\n--- RECONCILIATION REPORT ---")
    print(json.dumps(recon, indent=2))

    perf = strategy_performance_report(conn)
    print("\n--- STRATEGY PERFORMANCE REPORT ---")
    print(json.dumps(perf, indent=2))

    conn.close()


if __name__ == "__main__":
    populate_ledger()
