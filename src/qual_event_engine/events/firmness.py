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
        FirmnessLevel.RUMOUR: "Media speculation, unconfirmed market rumors, anonymous sources.",
        FirmnessLevel.INTENTION: "Management forward-looking statements, concall commentary, uncommitted MoUs.",
        FirmnessLevel.L1_PREFERRED: "Lowest bidder declaration (L1 status) prior to formal contract award.",
        FirmnessLevel.AWARD_LOA: "Award / LOA with entity and value, pending manual validation.",
        FirmnessLevel.BINDING_CONTRACT: "Board approved resolution, definitive agreement or binding MoU identified.",
        FirmnessLevel.EXECUTION_EVIDENCE: "Signed commercial contract, purchase order, work order, or final regulatory approval.",
    }

    @classmethod
    def evaluate(cls, event_type: str, headline: str, raw_text: str = "") -> FirmnessEvaluation:
        text = f"{headline} {raw_text}".upper()

        if any(w in text for w in ["SIGNED CONTRACT", "PURCHASE ORDER", "WORK ORDER", "FINAL APPROVAL", "EXECUTED AGREEMENT"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.EXECUTION_EVIDENCE,
                score=5,
                is_binding=True,
                evidence_required=cls.STANDARDS[FirmnessLevel.EXECUTION_EVIDENCE],
                rationale="Fully executed binding agreement or purchase order identified.",
            )

        if any(w in text for w in ["BOARD APPROVED", "BINDING MOU", "DEFINITIVE AGREEMENT"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.BINDING_CONTRACT,
                score=4,
                is_binding=True,
                evidence_required=cls.STANDARDS[FirmnessLevel.BINDING_CONTRACT],
                rationale="Board approved resolution or binding MoU identified.",
            )

        if any(w in text for w in ["AWARD", "LETTER OF AWARD", "LOA"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.AWARD_LOA,
                score=3,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.AWARD_LOA],
                rationale="Award / LOA identified, pending manual validation.",
            )

        if any(w in text for w in ["L1 BIDDER", "LOWEST BIDDER", "L-1"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.L1_PREFERRED,
                score=2,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.L1_PREFERRED],
                rationale="L1 / lowest bidder status confirmed, pending formal award.",
            )

        if any(w in text for w in ["PLANS TO", "INTENDS TO", "CONSIDERING", "EXPLORING", "SUBMITTED BID", "PARTICIPATED IN TENDER", "BIDDER"]):
            return FirmnessEvaluation(
                level=FirmnessLevel.INTENTION,
                score=1,
                is_binding=False,
                evidence_required=cls.STANDARDS[FirmnessLevel.INTENTION],
                rationale="Expression of management intent or forward-looking exploration.",
            )

        return FirmnessEvaluation(
            level=FirmnessLevel.RUMOUR,
            score=0,
            is_binding=False,
            evidence_required=cls.STANDARDS[FirmnessLevel.RUMOUR],
            rationale="Unconfirmed report or speculative headline.",
        )
