from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qual_event_engine.config import load_strategy_book
from qual_event_engine.decisions.service import (
    create_paper_intents,
    process_unassessed_events,
    record_review,
)
from qual_event_engine.domain.models import Assessment, ManualEvent
from qual_event_engine.events.service import ingest_event
from qual_event_engine.intelligence.analyst import Analyst, ExtractedFactItem
from qual_event_engine.market.reference import import_membership
from qual_event_engine.persistence.database import initialise, transaction
from qual_event_engine.persistence.repositories import insert_job


class SpyAnalyst(Analyst):
    """Spy wrapper around Analyst to verify assess() is NEVER called if grounding fails."""

    def __init__(
        self,
        mock_assessment: Assessment | None = None,
        mock_facts: list[ExtractedFactItem] | None = None,
    ) -> None:
        super().__init__(
            api_key=None,
            model_id="spy-model",
            timeout_seconds=5.0,
            mock_assessment=mock_assessment,
            mock_facts=mock_facts,
        )
        self.assess_called_count: int = 0
        self.extract_called_count: int = 0

    def extract_facts(self, raw_document_text: str, structured_context: dict[str, Any]) -> Any:
        self.extract_called_count += 1
        return super().extract_facts(raw_document_text, structured_context)

    def assess(self, event: dict[str, Any], evidence: Any, point_in_time_dossier: dict[str, Any] | None = None) -> Any:
        self.assess_called_count += 1
        return super().assess(event, evidence, point_in_time_dossier)


def _setup_test_universe(db_path: Path, tmp_path: Path, now: datetime) -> None:
    mem_file = tmp_path / "membership.jsonl"
    mem_file.write_text(
        (
            '{"symbol":"INTEGCO","legal_name":"Integration Corp Ltd",'
            f'"effective_from_utc":"{(now - timedelta(days=5)).isoformat()}",'
            '"series":"EQ","listed_status":"ACTIVE","surveillance_status":"NONE",'
            '"price_band_pct":10,"market_cap_inr":25000000000,"adv20_shares":400000,'
            '"adt20_inr":40000000,"eligible":true,"eligibility_reasons":[],'
            '"source_id":"fixture","source_version":"1","isin":"INE888A01018"}\n'
        ),
        encoding="utf-8",
    )
    with transaction(db_path) as conn:
        import_membership(conn, mem_file)


def test_production_pipeline_success_end_to_end(tmp_path: Path) -> None:
    """Exercises REAL production pipeline:
    Raw Document -> Stage 1 extract_facts() -> verbatim grounding validation ->
    validated facts -> Stage 2 assess() -> risk gates -> review -> paper intent.
    """
    db_path = tmp_path / "pipeline_success.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    initialise(db_path)

    now = datetime.now(UTC)
    _setup_test_universe(db_path, tmp_path, now)

    # 1. Raw Document with genuine verifiable text
    doc_path = drop_root / "exchange" / "filing.txt"
    doc_path.parent.mkdir(parents=True)
    filing_text = (
        "Integration Corp Ltd has been awarded a landmark EPC contract valued at INR 500 Crores "
        "by the National Highways Authority. The contract execution period is 24 months."
    )
    doc_path.write_text(filing_text, encoding="utf-8")

    event = ManualEvent.model_validate(
        {
            "source_native_id": "epc-500",
            "source_url": "https://exchange.test/epc-500",
            "source_published_at_utc": now.isoformat(),
            "document_path": "exchange/filing.txt",
            "event_type": "ORDER_WIN",
            "symbol": "INTEGCO",
            "isin": "INE888A01018",
            "legal_name": "Integration Corp Ltd",
            "headline": "Awarded landmark EPC contract valued at INR 500 Crores",
            "event_status": "FINAL",
            "firmness_level": 5,
            "event_value_inr": 500_000_000,
            "ttm_revenue_inr": 2_000_000_000,
            "entity_verified": True,
            "evidence_pages": [1],
        }
    )

    strategies_raw, config_hash = load_strategy_book(Path("."))
    # Enable strategies for test fixture
    strategies = {k: v.model_copy(update={"enabled": True}) for k, v in strategies_raw.strategies.items()}

    with transaction(db_path) as conn:
        job_id = insert_job(conn, "integ-job", config_hash)
        event_id, created = ingest_event(conn, event, "exchange", drop_root, archive_root, job_id)
        assert created

        # Valid facts strictly grounded in filing_text
        valid_facts = [
            ExtractedFactItem(
                field_name="contract_value",
                value="INR 500 Crores",
                evidence_text="INR 500 Crores",
                confidence=1.0,
            ),
            ExtractedFactItem(
                field_name="counterparty",
                value="National Highways Authority",
                evidence_text="National Highways Authority",
                confidence=1.0,
            ),
        ]

        spy_analyst = SpyAnalyst(
            mock_assessment=Assessment(
                recommendation="BUY_CANDIDATE",
                rationale="Grounded EPC contract award representing 25% of TTM revenue.",
                invalidating_fact="Cancellation or cost overrun",
                confidence="HIGH",
                model_id="spy-model",
                prompt_version="v1",
            ),
            mock_facts=valid_facts,
        )

        # Execute the real production pipeline
        processed = process_unassessed_events(conn, spy_analyst, strategies)
        assert processed == 1

        # Verify Stage 1 and Stage 2 were both executed
        assert spy_analyst.extract_called_count == 1
        assert spy_analyst.assess_called_count == 1

        # Check that facts were saved with VERIFIED status
        facts_db = conn.execute(
            "SELECT field_name, validation_status FROM extracted_fact WHERE event_id=? AND field_name IN ('contract_value', 'counterparty')",
            (event_id,),
        ).fetchall()
        assert len(facts_db) == 2
        for f in facts_db:
            assert f["validation_status"] == "VERIFIED"

        # Check analyst_assessment was created
        assessment_db = conn.execute(
            "SELECT recommendation, semantic_valid FROM analyst_assessment WHERE event_id=?",
            (event_id,),
        ).fetchone()
        assert assessment_db is not None
        assert assessment_db["recommendation"] == "BUY_CANDIDATE"
        assert assessment_db["semantic_valid"] == 1

        # Check event_state is REVIEW_PENDING
        ev = conn.execute("SELECT event_state FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()
        assert ev["event_state"] == "REVIEW_PENDING"

        # Step: Human review
        record_review(conn, event_id, "senior_analyst", "APPROVE", "Grounded primary evidence verified")
        ev_approved = conn.execute("SELECT event_state FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()
        assert ev_approved["event_state"] in ("APPROVED", "APPROVED_PAPER_INTENT")

        # Step: Create paper intent
        orders_created = create_paper_intents(conn, strategies, 10_000_000)
        assert orders_created >= 1

        # Verify paper_order row exists
        po = conn.execute("SELECT * FROM paper_order WHERE event_id=?", (event_id,)).fetchone()
        assert po is not None
        assert po["status"] == "PENDING_PRICE"
        assert po["symbol"] == "INTEGCO"


def test_production_pipeline_rejection_when_ungrounded(tmp_path: Path) -> None:
    """Proves Stage 2 is IMPOSSIBLE when Stage 1 grounding fails:
    If extracted fact contains hallucinated/ungrounded citation,
    process_unassessed_events MUST block the event and NEVER call Stage 2 assess().
    """
    db_path = tmp_path / "pipeline_ungrounded.db"
    drop_root = tmp_path / "drop"
    archive_root = tmp_path / "archive"
    initialise(db_path)

    now = datetime.now(UTC)
    _setup_test_universe(db_path, tmp_path, now)

    # 1. Raw Document with genuine text
    doc_path = drop_root / "exchange" / "filing.txt"
    doc_path.parent.mkdir(parents=True)
    filing_text = "Integration Corp Ltd reports routine quarterly maintenance at plant 1."
    doc_path.write_text(filing_text, encoding="utf-8")

    event = ManualEvent.model_validate(
        {
            "source_native_id": "maint-001",
            "source_url": "https://exchange.test/maint-001",
            "source_published_at_utc": now.isoformat(),
            "document_path": "exchange/filing.txt",
            "event_type": "ORDER_WIN",
            "symbol": "INTEGCO",
            "isin": "INE888A01018",
            "legal_name": "Integration Corp Ltd",
            "headline": "Routine maintenance filing",
            "event_status": "FINAL",
            "firmness_level": 5,
            "event_value_inr": 500_000_000,
            "ttm_revenue_inr": 2_000_000_000,
            "entity_verified": True,
            "evidence_pages": [1],
        }
    )

    strategies_raw, config_hash = load_strategy_book(Path("."))
    strategies = {k: v.model_copy(update={"enabled": True}) for k, v in strategies_raw.strategies.items()}

    with transaction(db_path) as conn:
        job_id = insert_job(conn, "ungrounded-job", config_hash)
        event_id, created = ingest_event(conn, event, "exchange", drop_root, archive_root, job_id)
        assert created

        # Hallucinated fact NOT in the filing text
        hallucinated_facts = [
            ExtractedFactItem(
                field_name="contract_value",
                value="INR 500 Crores Mega Contract",
                evidence_text="INR 500 Crores Mega Contract awarded by Defense Ministry",  # NOT in filing!
                confidence=0.99,
            )
        ]

        spy_analyst = SpyAnalyst(
            mock_assessment=Assessment(
                recommendation="BUY_CANDIDATE",
                rationale="Fabricated rationale that should NEVER be reached.",
                invalidating_fact="None",
                confidence="HIGH",
                model_id="spy-model",
                prompt_version="v1",
            ),
            mock_facts=hallucinated_facts,
        )

        # Execute the real production pipeline
        processed = process_unassessed_events(conn, spy_analyst, strategies)
        assert processed == 1

        # Stage 1 extract_facts WAS called
        assert spy_analyst.extract_called_count == 1

        # HARD PROOF: Stage 2 assess() MUST NEVER BE CALLED!
        assert spy_analyst.assess_called_count == 0, (
            f"CRITICAL: Stage 2 assess() was called {spy_analyst.assess_called_count} times! "
            "Stage 2 MUST BE IMPOSSIBLE when Stage 1 grounding fails."
        )

        # HARD PROOF: analyst_assessment table MUST have 0 rows for this event
        assessment_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM analyst_assessment WHERE event_id=?", (event_id,)
        ).fetchone()
        assert assessment_row["cnt"] == 0

        # Check that fact was stored as UNGROUNDED
        fact_db = conn.execute(
            "SELECT validation_status FROM extracted_fact WHERE event_id=? AND field_name='contract_value'",
            (event_id,),
        ).fetchone()
        assert fact_db is not None
        assert fact_db["validation_status"] == "UNGROUNDED"

        # Check that event was BLOCKED
        ev = conn.execute("SELECT event_state FROM canonical_event WHERE event_id=?", (event_id,)).fetchone()
        assert ev["event_state"] == "BLOCKED"

        # Check grounding_validation failure record
        gv = conn.execute(
            "SELECT * FROM extracted_fact WHERE event_id=? AND field_name='grounding_validation'",
            (event_id,),
        ).fetchone()
        assert gv is not None
        assert gv["validation_status"] == "BLOCKED"

        # Verify no paper intent can ever be created
        orders = create_paper_intents(conn, strategies, 10_000_000)
        assert orders == 0
        total_orders = conn.execute("SELECT COUNT(*) as cnt FROM paper_order WHERE event_id=?", (event_id,)).fetchone()
        assert total_orders["cnt"] == 0
