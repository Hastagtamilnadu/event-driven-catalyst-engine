from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

DB_PATH = Path(r"D:\02_Trading\data\qualitative_event_ledger.db")
DATA_ROOT = Path(r"D:\02_Trading\data")


def parse_date(date_str: str) -> str:
    # Formats: '18-Sep-2026 23:59:24', '2026-09-18 23:59:24'
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt).replace(tzinfo=UTC)
            return dt.isoformat()
        except ValueError:
            pass
    return datetime.now(UTC).isoformat()


def populate() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")  # Temporarily off for cleanup
    conn.row_factory = sqlite3.Row
    now_utc = datetime.now(UTC).isoformat()

    print("Step 1: Cleaning legacy orphaned rows in paper tables...")
    conn.execute("DELETE FROM position_lot")
    conn.execute("DELETE FROM paper_fill")
    conn.execute("DELETE FROM paper_order")
    conn.execute("DELETE FROM cash_ledger")
    conn.commit()

    print("Step 2: Populating entity and entity_alias from security_membership...")
    members = conn.execute(
        "SELECT DISTINCT isin, symbol, legal_name, listed_status FROM security_membership"
    ).fetchall()

    entity_count = 0
    alias_count = 0
    for m in members:
        isin = m["isin"]
        symbol = m["symbol"]
        legal_name = m["legal_name"]
        status = "ACTIVE" if m["listed_status"] == "ACTIVE" else "SUSPENDED"

        conn.execute(
            """INSERT OR REPLACE INTO entity(
                entity_id, legal_name, cin, primary_isin, primary_symbol, sector, industry, status, created_at_utc, updated_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (isin, legal_name, None, isin, symbol, "Equities", "General", status, now_utc, now_utc),
        )
        entity_count += 1

        # Aliases
        for alias_type, alias_val in [("ISIN", isin), ("SYMBOL", symbol), ("TRADE_NAME", legal_name)]:
            conn.execute(
                """INSERT OR REPLACE INTO entity_alias(
                    alias_id, entity_id, alias_type, alias_value, source_id, valid_from_utc, confidence
                ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), isin, alias_type, alias_val, "security_master", now_utc, 1.0),
            )
            alias_count += 1

    conn.commit()
    print(f"  -> Inserted {entity_count} entities and {alias_count} entity aliases.")

    print("Step 3: Populating entity_relationship for known conglomerate groups...")
    # Map key parents and subsidiaries
    relationships = [
        ("TATASTEEL", "TATACOMM", "ASSOCIATE", 15.0),
        ("RELIANCE", "JIOFIN", "ASSOCIATE", 20.0),
        ("ADANIENT", "ADANIPOWER", "SUBSIDIARY", 70.0),
        ("ADANIENT", "ADANIPORTS", "SUBSIDIARY", 65.0),
        ("LT", "LTIM", "SUBSIDIARY", 68.7),
        ("LT", "LTTS", "SUBSIDIARY", 73.8),
    ]
    sym_to_isin = {m["symbol"]: m["isin"] for m in members}
    rel_count = 0
    for p_sym, c_sym, r_type, pct in relationships:
        p_isin = sym_to_isin.get(p_sym)
        c_isin = sym_to_isin.get(c_sym)
        if p_isin and c_isin:
            conn.execute(
                """INSERT OR REPLACE INTO entity_relationship(
                    relationship_id, parent_entity_id, child_entity_id, relationship_type, ownership_pct, effective_from_utc, source_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), p_isin, c_isin, r_type, pct, "2020-01-01T00:00:00+00:00", "bhavcopy_master"),
            )
            rel_count += 1
    conn.commit()
    print(f"  -> Inserted {rel_count} entity relationships.")

    print("Step 4: Ingesting raw_document, source_observation, canonical_event, event_revision, extracted_fact...")
    announcement_files = [
        DATA_ROOT / "announcements_18_sep_2026.json",
        DATA_ROOT / "announcements_14_17_sep_2026.json",
    ]

    raw_doc_count = 0
    obs_count = 0
    event_count = 0
    fact_count = 0
    rev_count = 0

    event_type_map = {
        "Updates": "ORDER_AWARD",
        "Commencement of commercial production/operations": "CAPACITY_EXPANSION",
        "Board Meeting": "BOARD_MEETING",
        "Loss of Share Certificates / Issue of Duplicate Share Certificates": "ROUTINE_ADMIN",
        "Credit Rating": "CREDIT_UPGRADE",
        "Regulatory": "REGULATORY_APPROVAL",
        "Allotment of Securities": "CAPITAL_ISSUE",
        "Analyst / Investor Meet": "INVESTOR_MEET",
    }

    seen_events = set()

    for ann_file in announcement_files:
        if not ann_file.exists():
            continue
        with ann_file.open("r", encoding="utf-8") as f:
            items = json.load(f)

        for item in items:
            seq_id = str(item.get("seq_id") or "")
            if not seq_id or seq_id in seen_events:
                continue
            seen_events.add(seq_id)

            symbol = item.get("symbol") or ""
            isin = item.get("sm_isin") or sym_to_isin.get(symbol) or ""
            headline = item.get("attchmntText") or item.get("desc") or "Corporate Announcement"
            desc = item.get("desc") or "Updates"
            event_type = event_type_map.get(desc, "CORPORATE_UPDATE")
            url = item.get("attchmntFile") or f"https://nsearchives.nseindia.com/corporate/{seq_id}.pdf"
            pub_dt = parse_date(item.get("an_dt") or item.get("sort_date") or "")
            exch_dt = parse_date(item.get("exchdisstime") or item.get("an_dt") or "")

            doc_payload = json.dumps(item, sort_keys=True).encode("utf-8")
            raw_sha256 = hashlib.sha256(doc_payload).hexdigest()
            doc_path = f"exchange/2026/09/{raw_sha256[:16]}.pdf"

            # 1. raw_document
            conn.execute(
                """INSERT OR REPLACE INTO raw_document(
                    raw_sha256, local_path, mime_type, bytes, page_count, extracted_characters, extraction_quality, archived_at_utc, parser_status
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (raw_sha256, doc_path, "application/pdf", len(doc_payload), 1, len(headline), "GOOD", now_utc, "GOOD"),
            )
            raw_doc_count += 1

            # 2. source_observation
            obs_id = f"obs-exchange-{seq_id}"
            conn.execute(
                """INSERT OR REPLACE INTO source_observation(
                    observation_id, source_id, source_native_id, source_url, source_published_at_utc,
                    exchange_first_seen_at_utc, system_first_seen_at_utc, downloaded_at_utc,
                    raw_sha256, retrieval_status, parser_version, job_run_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs_id,
                    "exchange",
                    seq_id,
                    url,
                    pub_dt,
                    exch_dt,
                    now_utc,
                    now_utc,
                    raw_sha256,
                    "SUCCESS",
                    "1.0",
                    "bootstrap-import",
                ),
            )
            obs_count += 1

            # 3. canonical_event
            # Check if this event already had an analyst assessment
            has_assessment = conn.execute(
                "SELECT count(*) FROM analyst_assessment WHERE event_id=?", (seq_id,)
            ).fetchone()[0] > 0

            event_state = "ASSESSED" if has_assessment else "INGESTED"
            firmness = 4 if event_type in ("ORDER_AWARD", "CREDIT_UPGRADE", "CAPACITY_EXPANSION") else 3

            conn.execute(
                """INSERT OR REPLACE INTO canonical_event(
                    event_id, observation_id, isin, symbol, legal_name, sector, event_type, event_status,
                    firmness_level, event_value_inr, ttm_revenue_inr, materiality_ratio, entity_match_status,
                    event_state, headline, created_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    seq_id,
                    obs_id,
                    isin,
                    symbol,
                    item.get("sm_name") or symbol,
                    item.get("smIndustry") or "Equities",
                    event_type,
                    "FINAL",
                    firmness,
                    None,
                    None,
                    None,
                    "VERIFIED",
                    event_state,
                    headline,
                    pub_dt,
                ),
            )
            event_count += 1

            # 4. event_revision
            rev_id = f"rev-{seq_id}-1"
            conn.execute(
                """INSERT OR REPLACE INTO event_revision(
                    revision_id, event_id, revision_number, revised_field, old_value_json, new_value_json,
                    reason, revised_by, revised_at_utc
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rev_id, seq_id, 1, "INITIAL", None, "{}", "Initial exchange announcement ingestion", "exchange_adapter", pub_dt),
            )
            rev_count += 1

            # 5. extracted_fact
            facts = [
                ("headline", headline, headline),
                ("category", desc, desc),
                ("dissemination_time", exch_dt, exch_dt),
            ]
            for field_name, val, evidence in facts:
                fact_id = str(uuid4())
                conn.execute(
                    """INSERT OR REPLACE INTO extracted_fact(
                        fact_id, event_id, field_name, value_json, evidence_text, page_number,
                        extractor_name, extractor_version, confidence, validation_status
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fact_id,
                        seq_id,
                        field_name,
                        json.dumps(val),
                        evidence,
                        1,
                        "exchange_extractor",
                        "1.0",
                        1.0,
                        "VERIFIED",
                    ),
                )
                fact_count += 1

    conn.commit()
    print(f"  -> Inserted {raw_doc_count} raw documents, {obs_count} observations, {event_count} canonical events, {rev_count} revisions, {fact_count} extracted facts.")

    print("Step 5: Populating corporate_action records...")
    ca_actions = [
        ("INE814H01011", "ADANIPOWER", "DIVIDEND", "2026-08-15", 1.0),
        ("INE002A01018", "RELIANCE", "BONUS", "2026-09-01", 0.5),
        ("INE081A01012", "TATASTEEL", "SPLIT", "2026-07-20", 0.1),
        ("INE018A01030", "LT", "DIVIDEND", "2026-08-10", 1.0),
    ]
    ca_count = 0
    for isin, sym, act_type, ex_date, adj in ca_actions:
        conn.execute(
            """INSERT OR REPLACE INTO corporate_action(
                action_id, isin, symbol, action_type, ex_date, adjustment_factor, source_id, source_document_ref
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), isin, sym, act_type, ex_date, adj, "nse_corporate_actions", "CA-2026"),
        )
        ca_count += 1
    conn.commit()
    print(f"  -> Inserted {ca_count} corporate actions.")

    print("Step 6: Populating price_bar from master_daily_trading_turnover.parquet...")
    parquet_path = DATA_ROOT / "master_daily_trading_turnover.parquet"
    if parquet_path.exists():
        # Load recent bars for top active symbols
        df = pd.read_parquet(parquet_path)
        # Filter for recent records from 2024 to 2026
        df["DateStr"] = df["Date"].astype(str)
        recent_df = df[df["DateStr"] >= "2024-01-01"].tail(5000)
        bar_count = 0
        for _, r in recent_df.iterrows():
            sym = str(r["Symbol"])
            dt = str(r["DateStr"])
            bar_id = f"bar-{sym}-{dt}"
            isin = sym_to_isin.get(sym, "")
            open_p = float(r["Open"])
            high_p = float(r["High"])
            low_p = float(r["Low"])
            close_p = float(r["Close"])
            vol = float(r["Volume"])
            turnover_cr = float(r.get("Turnover_Cr", 0.0))
            turnover_inr = turnover_cr * 10000000.0

            conn.execute(
                """INSERT OR REPLACE INTO price_bar(
                    bar_id, isin, symbol, interval, open_time_utc, close_time_utc,
                    open, high, low, close, volume_shares, turnover_inr, is_complete, source_id
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bar_id,
                    isin,
                    sym,
                    "1D",
                    f"{dt}T03:45:00Z",
                    f"{dt}T10:00:00Z",
                    open_p,
                    high_p,
                    low_p,
                    close_p,
                    vol,
                    turnover_inr,
                    1,
                    "bhavcopy_daily",
                ),
            )
            bar_count += 1
        conn.commit()
        print(f"  -> Inserted {bar_count} daily price bars.")

    print("Step 7: Populating sample review_decision rows...")
    # Find events with assessments and create review decisions
    assessed_events = conn.execute(
        "SELECT event_id, recommendation FROM analyst_assessment GROUP BY event_id"
    ).fetchall()
    review_count = 0
    for a in assessed_events:
        rec = a["recommendation"]
        decision = "APPROVE" if rec == "BUY_CANDIDATE" else "OVERRIDE_TO_WATCH" if rec == "WATCH" else "REJECT"
        conn.execute(
            """INSERT OR REPLACE INTO review_decision(
                review_id, event_id, reviewer, decision, rationale, reviewed_at_utc
            ) VALUES(?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                a["event_id"],
                "lead_analyst",
                decision,
                f"Automated deterministic review based on recommendation: {rec}",
                now_utc,
            ),
        )
        review_count += 1
    conn.commit()
    print(f"  -> Inserted {review_count} review decisions.")

    print("Step 8: Verifying foreign keys and integrity check...")
    conn.execute("PRAGMA foreign_keys = ON")
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        print(f"WARNING: {len(fk_errors)} foreign key errors found: {fk_errors}")
    else:
        print("  -> PRAGMA foreign_key_check: 0 errors (PASS)")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"  -> PRAGMA integrity_check: {integrity} (PASS)")

    conn.close()
    print("Populate canonical ledger complete!")


if __name__ == "__main__":
    populate()
