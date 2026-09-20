from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qual_event_engine.domain.models import Assessment


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    hallucination_detected: bool
    rejection_reasons: list[str]


class SemanticValidator:
    """Deterministic validation engine enforcing AI grounding and business logic consistency (§31)."""

    def verify_grounding(self, extracted_quote: str, raw_document_text: str) -> bool:
        """Asserts that extracted quote exists verbatim within the raw source text."""
        if not extracted_quote or not extracted_quote.strip():
            return False
        # Normalize whitespace for robust comparison
        norm_quote = " ".join(extracted_quote.strip().split())
        norm_doc = " ".join(raw_document_text.split())
        return norm_quote in norm_doc

    def validate_assessment(
        self,
        event: dict[str, Any],
        assessment: Assessment,
        extracted_facts: list[dict[str, Any]],
        raw_document_text: str,
    ) -> ValidationResult:
        reasons: list[str] = []
        hallucination = False

        # 1. Grounding check on all extracted evidence quotes
        for fact in extracted_facts:
            quote = fact.get("evidence_text", "")
            if quote and not self.verify_grounding(quote, raw_document_text):
                hallucination = True
                reasons.append(f"Fact '{fact.get('field_name')}' contains ungrounded citation.")

        # 2. Archetype-specific business logic checks
        event_type = event.get("event_type", "")
        firmness = int(event.get("firmness_level", 0))

        # Check: BUY_CANDIDATE requires minimum firmness level 4
        if assessment.recommendation == "BUY_CANDIDATE" and firmness < 4:
            reasons.append(
                f"BUY_CANDIDATE recommendation requires firmness level >= 4 (actual: {firmness})"
            )

        # Check: Negative governance must never result in BUY_CANDIDATE or WATCH
        if event_type == "NEGATIVE_GOVERNANCE" and assessment.recommendation in (
            "BUY_CANDIDATE",
            "WATCH",
        ):
            reasons.append("NEGATIVE_GOVERNANCE event cannot receive BUY_CANDIDATE or WATCH")

        # Check: USFDA warning letter must not be BUY_CANDIDATE
        if event_type == "USFDA_WARNING_LETTER" and assessment.recommendation == "BUY_CANDIDATE":
            reasons.append("USFDA_WARNING_LETTER event cannot receive BUY_CANDIDATE")

        # Check: Entity match must be verified for BUY_CANDIDATE
        entity_status = event.get("entity_match_status", "")
        if assessment.recommendation == "BUY_CANDIDATE" and entity_status != "VERIFIED":
            reasons.append("BUY_CANDIDATE requires entity_match_status == 'VERIFIED'")

        is_valid = len(reasons) == 0 and not hallucination
        return ValidationResult(
            is_valid=is_valid,
            hallucination_detected=hallucination,
            rejection_reasons=reasons,
        )
