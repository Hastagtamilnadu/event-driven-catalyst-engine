from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from qual_event_engine.decisions.service import (
    create_paper_intents,
    process_unassessed_events,
    record_review,
)
from qual_event_engine.domain.models import Assessment, ManualEvent, StrategyConfig
from qual_event_engine.events.service import ingest_event
from qual_event_engine.intelligence.analyst import Analyst
from qual_event_engine.market.reference import import_membership
from qual_event_engine.paper.service import MarketBar, import_market_bars, process_pending_orders
from qual_event_engine.persistence.database import connect, initialise, transaction
from qual_event_engine.persistence.repositories import insert_job


def _mock_analyst() -> Analyst:
    return Analyst(
        None,
        "unused",
        1,
        mock_assessment=Assessment(
            recommendation="BUY_CANDIDATE",
            rationale="Valid upgrade confirmed by rating rationale.",
            invalidating_fact="None",
            confidence="HIGH",
            model_id="mock-gemini",
            prompt_version="mock-v1",
        ),
    )


def _event(now: datetime) -> ManualEvent:
    return ManualEvent.model_validate(
        {
            "source_native_id": "rating-1",
            "source_url": "https://example.test/rating-1",
            "source_published_at_utc": now.isoformat(),
            "document_path": "ratings/source.txt",
            "event_type": "CREDIT_UPGRADE",
            "symbol": "TESTCO",
            "isin": "INE000A01000",
            "legal_name": "Test Company Limited",
            "headline": "Rating upgraded from A to AA",
            "event_status": "FINAL",
            "firmness_level": 4,
            "sector": "Industrials",
            "previous_rating": "A",
            "new_rating": "AA",
            "entity_verified": True,
            "evidence_pages": [1],
        }
    )


def _strategy() -> dict[str, StrategyConfig]:
    return {
        "CR-01": StrategyConfig.model_validate(
            {
                "enabled": True,
                "event_types": ["CREDIT_UPGRADE"],
                "minimum_firmness_level": 4,
                "maximum_position_nav_pct": 2,
                "maximum_participation_pct": 1,
                "stop_loss_pct": 6,
                "time_stop_sessions": 20,
                "review_required": True,
            }
        )
    }


def _membership(path: Path, now: datetime) -> None:
    path.write_text(
        (
            "{"
            '"symbol":"TESTCO",'
            '"legal_name":"Test Company Limited",'
            f'"effective_from_utc":"{(now - timedelta(days=1)).isoformat()}",'
            '"series":"EQ",'
            '"listed_status":"ACTIVE",'
            '"surveillance_status":"NONE",'
            '"price_band_pct":10,'
            '"market_cap_inr":1000000000,'
            '"adv20_shares":100000,'
            '"adt20_inr":10000000,'
            '"eligible":true,'
            '"eligibility_reasons":[],'
            '"source_id":"fixture",'
            '"source_version":"1",'
            '"isin":"INE000A01000"'
            "}\n"
        ),
        encoding="utf-8",
    )


def test_event_to_review_to_paper_fill(tmp_path: Path) -> None:
    db_path = tmp_path / "engine.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    document = drop_root / "ratings" / "source.txt"
    document.parent.mkdir(parents=True)
    document.write_text("Official rating rationale: upgrade to AA.", encoding="utf-8")
    initialise(db_path)
    now = datetime.now(UTC)
    with transaction(db_path) as connection:
        membership_path = tmp_path / "membership.jsonl"
        _membership(membership_path, now)
        assert import_membership(connection, membership_path) == 1
        job_id = insert_job(connection, "test", "test-config")
        event_id, created = ingest_event(
            connection, _event(now), "ratings", drop_root, archive_root, job_id
        )
        assert created
        _, duplicate = ingest_event(
            connection, _event(now), "ratings", drop_root, archive_root, job_id
        )
        assert not duplicate
        assert process_unassessed_events(connection, _mock_analyst(), _strategy()) == 1
        assert record_review(connection, event_id, "tester", "APPROVE", "Primary evidence checked")
        assert create_paper_intents(connection, _strategy(), 1_000_000) == 1

    bars = tmp_path / "bars.jsonl"
    later = now + timedelta(minutes=1)
    bars.write_text(
        MarketBar(
            symbol="TESTCO",
            open_time_utc=later,
            close_time_utc=later + timedelta(minutes=1),
            open=100,
            high=101,
            low=99,
            close=100,
            volume_shares=5000,
            turnover_inr=500_000,
            source_id="fixture",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    with transaction(db_path) as connection:
        assert import_market_bars(connection, bars) == 1
        result = process_pending_orders(connection, _strategy(), 1_000_000)
        assert result["filled"] == 1
    with connect(db_path) as connection:
        position = connection.execute("SELECT * FROM position_lot WHERE status='OPEN'").fetchone()
        assert position is not None
        assert position["strategy_id"] == "CR-01"


def test_unverified_entity_is_blocked(tmp_path: Path) -> None:
    db_path = tmp_path / "engine.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    document = drop_root / "ratings" / "source.txt"
    document.parent.mkdir(parents=True)
    document.write_text("Rating upgrade", encoding="utf-8")
    event = _event(datetime.now(UTC)).model_copy(update={"entity_verified": False})
    initialise(db_path)
    with transaction(db_path) as connection:
        job_id = insert_job(connection, "test", "test-config")
        event_id, _ = ingest_event(connection, event, "ratings", drop_root, archive_root, job_id)
        assert process_unassessed_events(connection, _mock_analyst(), _strategy()) == 1
        state = connection.execute(
            "SELECT event_state FROM canonical_event WHERE event_id=?", (event_id,)
        ).fetchone()
        assert state["event_state"] == "BLOCKED"
