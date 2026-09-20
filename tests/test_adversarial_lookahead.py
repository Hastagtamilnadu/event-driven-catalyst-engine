from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from qual_event_engine.config import load_strategy_book
from qual_event_engine.decisions.service import (
    create_paper_intents,
    process_unassessed_events,
    record_review,
)
from qual_event_engine.domain.models import Assessment, ManualEvent
from qual_event_engine.events.service import ingest_event
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.market.reference import import_membership
from qual_event_engine.paper.service import MarketBar, import_market_bars, process_pending_orders
from qual_event_engine.persistence.database import connect, initialise, transaction
from qual_event_engine.persistence.repositories import insert_job


def test_adversarial_lookahead_and_future_leak_prevention(tmp_path: Path) -> None:
    db_path = tmp_path / "lookahead_test.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    initialise(db_path)

    decision_time = datetime(2026, 9, 10, 10, 0, 0, tzinfo=UTC)
    future_time = datetime(2026, 9, 10, 15, 30, 0, tzinfo=UTC)  # 5.5 hours in the future!

    # 1. Setup Membership available prior to decision_time
    mem_file = tmp_path / "mem.jsonl"
    mem_file.write_text(
        (
            '{"symbol":"SECURECO","legal_name":"Secure Corp Ltd",'
            f'"effective_from_utc":"{(decision_time - timedelta(days=5)).isoformat()}",'
            '"series":"EQ","listed_status":"ACTIVE","surveillance_status":"NONE",'
            '"price_band_pct":10,"market_cap_inr":20000000000,"adv20_shares":300000,'
            '"adt20_inr":30000000,"eligible":true,"eligibility_reasons":[],'
            '"source_id":"fixture","source_version":"1","isin":"INE999A01019"}\n'
        ),
        encoding="utf-8",
    )
    with transaction(db_path) as conn:
        import_membership(conn, mem_file)

    # 2. Ingest valid historical event at decision_time
    doc_path = drop_root / "exchange" / "filing.txt"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text("Company announces contract award of INR 250 Crores.", encoding="utf-8")

    event = ManualEvent.model_validate(
        {
            "source_native_id": "filing-001",
            "source_url": "https://exchange.test/filing-001",
            "source_published_at_utc": decision_time.isoformat(),
            "document_path": "exchange/filing.txt",
            "event_type": "ORDER_WIN",
            "symbol": "SECURECO",
            "isin": "INE999A01019",
            "legal_name": "Secure Corp Ltd",
            "headline": "Contract award of INR 250 Crores",
            "event_status": "FINAL",
            "firmness_level": 5,
            "event_value_inr": 250_000_000,
            "ttm_revenue_inr": 1_000_000_000,
            "entity_verified": True,
            "evidence_pages": [1],
        }
    )

    strategies_raw, config_hash = load_strategy_book(Path("."))
    strategies = {k: v.model_copy(update={"enabled": True}) for k, v in strategies_raw.strategies.items()}

    with transaction(db_path) as conn:
        job_id = insert_job(conn, "adversarial-job", config_hash)
        event_id, created = ingest_event(conn, event, "exchange", drop_root, archive_root, job_id)
        assert created

    # 3. Adversarially attempt to inject a future forward-return column into the event
    with connect(db_path) as conn:
        event_row = conn.execute("SELECT * FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()
        assert "forward_return" not in dict(event_row)
        assert "forward_5d_return" not in dict(event_row)

    # 4. Adversarially inject a FUTURE market bar (e.g. at 15:30 UTC) BEFORE the order's valid window
    future_bar_file = tmp_path / "future_bars.jsonl"
    future_bar_file.write_text(
        MarketBar(
            symbol="SECURECO",
            open_time_utc=future_time,
            close_time_utc=future_time + timedelta(minutes=1),
            open=150.0,
            high=155.0,
            low=149.0,
            close=152.0,
            volume_shares=100000,
            turnover_inr=15200000,
            source_id="fixture",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    with transaction(db_path) as conn:
        import_market_bars(conn, future_bar_file)

    # 5. Process events and create paper intents valid from decision_time to decision_time + 10 mins
    analyst = Analyst(
        None,
        "unused",
        1,
        mock_assessment=Assessment(
            recommendation="BUY_CANDIDATE",
            rationale="Substantial contract win.",
            invalidating_fact="None",
            confidence="HIGH",
            model_id="mock-gemini",
            prompt_version="v1",
        ),
    )
    with transaction(db_path) as conn:
        process_unassessed_events(conn, analyst, strategies)
        record_review(conn, event_id, "lead_analyst", "APPROVE", "Verified")
        create_paper_intents(conn, strategies, 10_000_000)

        # Set the order's valid_until_utc strictly BEFORE future_time (e.g. decision_time + 10m)
        conn.execute(
            "UPDATE paper_order SET valid_from_utc=?, valid_until_utc=? WHERE event_id=?",
            (
                decision_time.isoformat(),
                (decision_time + timedelta(minutes=10)).isoformat(),
                event_id,
            ),
        )

        # 6. Run paper processing: The future bar (at 15:30) MUST NOT be used to fill the order!
        stats = process_pending_orders(
            conn, strategies, 10_000_000, as_of_utc=decision_time.isoformat()
        )
        # Order should remain UNFILLED because the only bar in the database is in the future
        assert stats["filled"] == 0
        assert stats["unfilled"] == 1

        order = conn.execute("SELECT * FROM paper_order WHERE event_id=?", (event_id,)).fetchone()
        assert order["status"] == "PENDING_PRICE"
        assert order["quantity_remaining"] == order["quantity_requested"]

    # 7. Now provide the legitimate contemporary bar within the window
    valid_bar_file = tmp_path / "valid_bars.jsonl"
    bar_time = decision_time + timedelta(minutes=2)
    valid_bar_file.write_text(
        MarketBar(
            symbol="SECURECO",
            open_time_utc=bar_time,
            close_time_utc=bar_time + timedelta(minutes=1),
            open=100.0,
            high=101.0,
            low=99.5,
            close=100.5,
            volume_shares=50000,
            turnover_inr=5025000,
            source_id="fixture",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    with transaction(db_path) as conn:
        import_market_bars(conn, valid_bar_file)
        stats2 = process_pending_orders(
            conn, strategies, 10_000_000, as_of_utc=(decision_time + timedelta(minutes=3)).isoformat()
        )
        assert stats2["filled"] == 1

        fill = conn.execute("SELECT * FROM paper_fill").fetchone()
        assert fill is not None
        # Must have filled at the valid contemporary bar price, NOT the future 150+ price
        assert fill["raw_price"] == 100.5

    # 8. Test Idempotency: re-running ingestion of the exact same event produces 0 duplicates
    with transaction(db_path) as conn:
        job_id_2 = insert_job(conn, "adversarial-job-2", config_hash)
        event_id_2, created_2 = ingest_event(conn, event, "exchange", drop_root, archive_root, job_id_2)
        assert created_2 is False
        assert event_id_2 == event_id

        # Assert no duplicate canonical event
        count = conn.execute("SELECT count(*) FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()[0]
        assert count == 1
