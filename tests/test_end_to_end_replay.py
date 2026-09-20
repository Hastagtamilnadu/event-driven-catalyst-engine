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


def test_full_archetype_end_to_end_pipeline(tmp_path: Path) -> None:
    db_path = tmp_path / "replay.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    initialise(db_path)

    now = datetime.now(UTC)

    # 1. Setup Membership
    membership_file = tmp_path / "membership.jsonl"
    membership_file.write_text(
        (
            '{"symbol":"INFRACO","legal_name":"Infra Construction Ltd",'
            f'"effective_from_utc":"{(now - timedelta(days=1)).isoformat()}",'
            '"series":"EQ","listed_status":"ACTIVE","surveillance_status":"NONE",'
            '"price_band_pct":10,"market_cap_inr":50000000000,"adv20_shares":500000,'
            '"adt20_inr":50000000,"eligible":true,"eligibility_reasons":[],'
            '"source_id":"fixture","source_version":"1","isin":"INE123A01010"}\n'
        ),
        encoding="utf-8",
    )
    with transaction(db_path) as conn:
        assert import_membership(conn, membership_file) == 1

    # 2. Ingest Events across Archetypes
    doc_path = drop_root / "exchange" / "order_win.txt"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text("Company secured a major order worth INR 600 Crores.", encoding="utf-8")

    event = ManualEvent.model_validate(
        {
            "source_native_id": "ord-101",
            "source_url": "https://exchange.test/announcements/ord-101",
            "source_published_at_utc": now.isoformat(),
            "document_path": "exchange/order_win.txt",
            "event_type": "ORDER_WIN",
            "symbol": "INFRACO",
            "isin": "INE123A01010",
            "legal_name": "Infra Construction Ltd",
            "headline": "Commercial order win of INR 600 Crores",
            "event_status": "FINAL",
            "firmness_level": 5,
            "event_value_inr": 600_000_000,
            "ttm_revenue_inr": 2_000_000_000,  # 30% materiality
            "entity_verified": True,
            "evidence_pages": [1],
        }
    )

    strategies_raw, _ = load_strategy_book(Path("."))
    strategies = {k: v.model_copy(update={"enabled": True}) for k, v in strategies_raw.strategies.items()}

    with transaction(db_path) as conn:
        job_id = insert_job(conn, "replay-job", "replay-config")
        event_id, created = ingest_event(
            conn, event, "exchange", drop_root, archive_root, job_id
        )
        assert created

        # Mock Analyst for OR-01
        analyst = Analyst(
            None,
            "unused",
            1,
            mock_assessment=Assessment(
                recommendation="BUY_CANDIDATE",
                rationale="Highly material order win of INR 600 Cr",
                invalidating_fact="None",
                confidence="HIGH",
                model_id="mock-gemini",
                prompt_version="v1",
            ),
        )

        assert process_unassessed_events(conn, analyst, strategies) == 1
        assert record_review(conn, event_id, "lead_analyst", "APPROVE", "Backlog ratio verified")
        assert create_paper_intents(conn, strategies, 10_000_000) == 1

    # 3. Process Market Bars & Paper Fill
    bars_file = tmp_path / "market_bars.jsonl"
    bar_time = now + timedelta(minutes=2)
    bars_file.write_text(
        MarketBar(
            symbol="INFRACO",
            open_time_utc=bar_time,
            close_time_utc=bar_time + timedelta(minutes=1),
            open=100.0,
            high=102.0,
            low=99.5,
            close=101.0,
            volume_shares=50000,
            turnover_inr=5_050_000,
            source_id="fixture",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    with transaction(db_path) as conn:
        assert import_market_bars(conn, bars_file) == 1
        result = process_pending_orders(conn, strategies, 10_000_000)
        assert result["filled"] == 1

    # 4. Verify Ledger State & Costs
    with connect(db_path) as conn:
        fill = conn.execute("SELECT * FROM paper_fill").fetchone()
        assert fill is not None
        assert fill["statutory_cost_inr"] > 0  # Verified Indian statutory cost deduction
        assert fill["spread_cost_inr"] > 0     # Half-spread cost deduction
        assert fill["impact_cost_inr"] > 0     # Market impact cost deduction

        pos = conn.execute("SELECT * FROM position_lot WHERE status='OPEN'").fetchone()
        assert pos is not None
        assert pos["symbol"] == "INFRACO"
        assert pos["strategy_id"] == "OR-01"

        cash = conn.execute("SELECT * FROM cash_ledger").fetchall()
        assert len(cash) >= 1
