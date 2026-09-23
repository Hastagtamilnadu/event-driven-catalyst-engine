from __future__ import annotations

import pytest

from qual_event_engine.domain.models import Assessment
from qual_event_engine.intelligence.validator import SemanticValidator

# 20 Corporate Announcement Benchmark Fixtures (§31)
BENCHMARK_FIXTURES = [
    # 1. High-firmness credit upgrade
    {
        "id": "FX-01",
        "doc": "CRISIL Ratings has upgraded its rating on bank facilities of Apex Industries to CRISIL AA from CRISIL A.",
        "event": {"event_type": "CREDIT_UPGRADE", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Two-notch upgrade confirmed",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "rating_text", "evidence_text": "upgraded its rating on bank facilities of Apex Industries to CRISIL AA from CRISIL A."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 2. Moderate credit upgrade
    {
        "id": "FX-02",
        "doc": "ICRA has upgraded long-term rating to [ICRA]A from [ICRA]BBB+.",
        "event": {"event_type": "CREDIT_UPGRADE", "firmness_level": 4, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Rating upgrade confirmed",
            invalidating_fact="None", confidence="MEDIUM", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "rating_text", "evidence_text": "upgraded long-term rating to [ICRA]A from [ICRA]BBB+."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 3. Credit downgrade (must not be BUY)
    {
        "id": "FX-03",
        "doc": "CARE has downgraded the credit rating to CARE A- from CARE AA-.",
        "event": {"event_type": "CREDIT_UPGRADE", "firmness_level": 2, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Erroneous buy on downgrade",
            invalidating_fact="None", confidence="LOW", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "rating_text", "evidence_text": "downgraded the credit rating to CARE A- from CARE AA-."}],
        "expected_valid": False,  # Firmness 2 < 4
        "expected_hallucination": False,
    },
    # 4. Large commercial order win
    {
        "id": "FX-04",
        "doc": "The company has secured an order worth INR 550 Crores from state electricity board.",
        "event": {"event_type": "ORDER_WIN", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Material order win confirmed",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "order_val", "evidence_text": "secured an order worth INR 550 Crores"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 5. Order win with undisclosed value (low firmness)
    {
        "id": "FX-05",
        "doc": "Company receives a significant domestic order from repeat client.",
        "event": {"event_type": "ORDER_WIN", "firmness_level": 2, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Order win",
            invalidating_fact="Undisclosed value", confidence="LOW", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "desc", "evidence_text": "receives a significant domestic order"}],
        "expected_valid": False,  # Firmness 2 < 4
        "expected_hallucination": False,
    },
    # 6. Order win with unverified entity
    {
        "id": "FX-06",
        "doc": "Order worth 200 Cr awarded.",
        "event": {"event_type": "ORDER_WIN", "firmness_level": 4, "entity_match_status": "UNMATCHED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Order win",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "val", "evidence_text": "Order worth 200 Cr awarded."}],
        "expected_valid": False,  # Unverified entity
        "expected_hallucination": False,
    },
    # 7. Government tender L1 bid (conditional firmness 3)
    {
        "id": "FX-07",
        "doc": "Company emerged as L1 bidder in NHAI highway project.",
        "event": {"event_type": "EXECUTED_CONTRACT", "firmness_level": 3, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="WATCH", rationale="L1 bidder status awaiting final LOA",
            invalidating_fact="Final LOA pending", confidence="MEDIUM", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "tender_status", "evidence_text": "emerged as L1 bidder in NHAI highway project."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 8. Executed government contract
    {
        "id": "FX-08",
        "doc": "Formal contract agreement executed with Ministry of Railways for INR 850 Cr.",
        "event": {"event_type": "EXECUTED_CONTRACT", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Executed contract with formal signing",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "contract", "evidence_text": "Formal contract agreement executed with Ministry of Railways"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 9. USFDA EIR with NAI (No Action Indicated)
    {
        "id": "FX-09",
        "doc": "USFDA inspection closed with Establishment Inspection Report designating NAI status.",
        "event": {"event_type": "USFDA_FINAL_CLASSIFICATION", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Full USFDA clearance with NAI",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "status", "evidence_text": "Establishment Inspection Report designating NAI status."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 10. USFDA Form 483 with observations (WATCH)
    {
        "id": "FX-10",
        "doc": "USFDA completed inspection and issued Form 483 with 3 procedural observations.",
        "event": {"event_type": "USFDA_FINAL_CLASSIFICATION", "firmness_level": 3, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="WATCH", rationale="Form 483 issued with 3 observations",
            invalidating_fact="Observations pending review", confidence="MEDIUM", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "obs", "evidence_text": "issued Form 483 with 3 procedural observations."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 11. USFDA Warning Letter (must BLOCK)
    {
        "id": "FX-11",
        "doc": "USFDA has issued a Warning Letter regarding cGMP violations at Facility 1.",
        "event": {"event_type": "USFDA_WARNING_LETTER", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Erroneous buy on warning letter",
            invalidating_fact="Warning Letter", confidence="LOW", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "alert", "evidence_text": "issued a Warning Letter"}],
        "expected_valid": False,  # USFDA Warning Letter cannot be BUY
        "expected_hallucination": False,
    },
    # 12. Negative Governance: Auditor Resignation
    {
        "id": "FX-12",
        "doc": "Statutory auditor has submitted resignation citing lack of sufficient audit evidence.",
        "event": {"event_type": "NEGATIVE_GOVERNANCE", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Erroneous buy on resignation",
            invalidating_fact="Auditor resignation", confidence="LOW", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "resignation", "evidence_text": "Statutory auditor has submitted resignation"}],
        "expected_valid": False,  # Negative governance cannot be BUY
        "expected_hallucination": False,
    },
    # 13. Negative Governance: Forensic Audit (PASS/BLOCK)
    {
        "id": "FX-13",
        "doc": "SEBI has ordered a forensic audit into the financial statements of the company.",
        "event": {"event_type": "NEGATIVE_GOVERNANCE", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BLOCK", rationale="SEBI forensic audit ordered",
            invalidating_fact="Forensic audit", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "audit", "evidence_text": "SEBI has ordered a forensic audit"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 14. Surveillance Action: ASM Stage 1 (BLOCK)
    {
        "id": "FX-14",
        "doc": "Security placed under Additional Surveillance Measure (ASM) Stage 1.",
        "event": {"event_type": "NEGATIVE_GOVERNANCE", "firmness_level": 4, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="PASS", rationale="ASM Stage 1 surveillance active",
            invalidating_fact="Surveillance active", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "asm", "evidence_text": "placed under Additional Surveillance Measure (ASM) Stage 1."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 15. Calendar Event: Early Earnings Pre-Announcement
    {
        "id": "FX-15",
        "doc": "Board meeting rescheduled earlier to October 10 from October 28 to consider quarterly results.",
        "event": {"event_type": "CALENDAR_EVENT", "firmness_level": 4, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Early results meeting indicates positive surprise potential",
            invalidating_fact="None", confidence="MEDIUM", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "meeting", "evidence_text": "Board meeting rescheduled earlier to October 10"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 16. Parivesh Environmental Clearance Approved
    {
        "id": "FX-16",
        "doc": "MoEFCC Parivesh portal grants final Environmental Clearance for 5 MTPA expansion.",
        "event": {"event_type": "ORDER_WIN", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Major capacity expansion clearance secured",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "ec", "evidence_text": "grants final Environmental Clearance for 5 MTPA expansion."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 17. Promoter Pledge Increase (WATCH)
    {
        "id": "FX-17",
        "doc": "Promoter group pledged additional 4.5% equity shares with lenders.",
        "event": {"event_type": "NEGATIVE_GOVERNANCE", "firmness_level": 4, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="PASS", rationale="Increased promoter encumbrance",
            invalidating_fact="Pledge increase", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "pledge", "evidence_text": "pledged additional 4.5% equity shares"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 18. Transcript Capacity Guidance (Context Only)
    {
        "id": "FX-18",
        "doc": "Management stated in Q3 earnings call that phase 2 commercial production will commence by Q1.",
        "event": {"event_type": "CALENDAR_EVENT", "firmness_level": 2, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="WATCH", rationale="Transcript context on capex",
            invalidating_fact="Unconfirmed timeline", confidence="LOW", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "call", "evidence_text": "phase 2 commercial production will commence"}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 19. Large Railway executed contract
    {
        "id": "FX-19",
        "doc": "Railways contract worth INR 1200 Crores signed today.",
        "event": {"event_type": "EXECUTED_CONTRACT", "firmness_level": 5, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Massive order win verified",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "val", "evidence_text": "Railways contract worth INR 1200 Crores signed today."}],
        "expected_valid": True,
        "expected_hallucination": False,
    },
    # 20. Ungrounded Fact Citation Test (Synthetic Hallucination - MUST FAIL)
    {
        "id": "FX-20",
        "doc": "Company announces appointment of new independent director.",
        "event": {"event_type": "CALENDAR_EVENT", "firmness_level": 4, "entity_match_status": "VERIFIED"},
        "assessment": Assessment(
            recommendation="BUY_CANDIDATE", rationale="Hallucinated order win",
            invalidating_fact="None", confidence="HIGH", model_id="test", prompt_version="v1"
        ),
        "facts": [{"field_name": "order_val", "evidence_text": "Company has secured an order of 900 Crores."}], # NOT in doc!
        "expected_valid": False,
        "expected_hallucination": True,
    },
]


from typing import Any


@pytest.mark.parametrize("fixture", BENCHMARK_FIXTURES, ids=[str(f["id"]) for f in BENCHMARK_FIXTURES])
def test_benchmark_fixture(fixture: dict[str, Any]) -> None:
    validator = SemanticValidator()
    result = validator.validate_assessment(
        event=fixture["event"],
        assessment=fixture["assessment"],
        extracted_facts=fixture["facts"],
        raw_document_text=fixture["doc"],
    )

    assert result.is_valid == fixture["expected_valid"], (
        f"Fixture {fixture['id']} failed validation expectation. "
        f"Rejection reasons: {result.rejection_reasons}"
    )
    assert result.hallucination_detected == fixture["expected_hallucination"], (
        f"Fixture {fixture['id']} failed hallucination expectation."
    )
