from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from qual_event_engine.domain.enums import FirmnessLevel


@dataclass(frozen=True, slots=True)
class FirmnessEvaluation:
    level: FirmnessLevel
    score: int
    is_binding: bool
    evidence_required: str
    rationale: str


class FirmnessEvaluator:
    """Evaluates the contractual firmness level (F0 - F5) of qualitative events."""

    STANDARDS: ClassVar[dict[FirmnessLevel, str]] = {
        FirmnessLevel.UNCONFIRMED_RUMOR: "Media speculation, unconfirmed market rumors, anonymous sources.",
        FirmnessLevel.MANAGEMENT_INTENT: "Management forward-looking statements, concall commentary, uncommitted MoUs.",
        FirmnessLevel.TENDER_PARTICIPATION: "Formal bid submission, RFP response, tender participation acknowledgment.",
        FirmnessLevel.L1_STATUS: "Lowest bidder declaration (L1 status) prior to formal contract award.",
        FirmnessLevel.BOARD_APPROVED_MOU: "Board approval granted, definitive agreement or binding MoU executed.",
        FirmnessLevel.EXECUTED_CONTRACT: "Signed commercial contract, purchase order, work order, or final regulatory approval.",
    }

    @classmethod
    def evaluate(cls, event_type: str, headline: str, raw_text: str = "") -> FirmnessEvaluation:
        text = f"{headline} {raw_text}".upper()

        if any(w in text for w in ["SIGNED CONTRACT", "PURCHASE ORDER", "WORK ORDER", "FINAL APPROVAL", "EXECUTED AGREEMENT"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.EXECUTED_CONTRACT,
                score=5,
                is_binding=True,
                evidence_required=cls.STANDARDS[FirmnessLevel.EXECUTED_CONTRACT],
                rationale="Fully executed binding agreement or purchase order identified.",
            )

        if any(w in text for w in ["BOARD APPROVED", "BINDING MOU", "DEFINITIVE AGREEMENT"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.BOARD_APPROVED_MOU,
                score=4,
                is_binding=True,
                evidence_required=cls.STANDARDS[FirmnessLevel.BOARD_APPROVED_MOU],
                rationale="Board approved resolution or binding MoU identified.",
            )

        if any(w in text for w in ["L1 BIDDER", "LOWEST BIDDER", "L-1"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.L1_STATUS,
                score=3,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.L1_STATUS],
                rationale="L1 / lowest bidder status confirmed, pending formal award.",
            )

        if any(w in text for w in ["SUBMITTED BID", "PARTICIPATED IN TENDER", "BIDDER"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.TENDER_PARTICIPATION,
                score=2,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.TENDER_PARTICIPATION],
                rationale="Tender participation or bid submission identified.",
            )

        if any(w in text for w in ["PLANS TO", "INTENDS TO", "CONSIDERING", "EXPLORING"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.MANAGEMENT_INTENT,
                score=1,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.MANAGEMENT_INTENT],
                rationale="Expression of management intent or forward-looking exploration.",
            )

        return FirmnessEvaluation(
            level=FirmnessLevel.UNCONFIRMED_RUMOR,
            score=0,
            is_binding=False,
            evidence_required=cls.STANDARDS[FirmnessLevel.UNCONFIRMED_RUMOR],
            rationale="Unconfirmed report or speculative headline.",
        )
