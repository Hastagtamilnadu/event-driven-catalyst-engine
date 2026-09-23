from __future__ import annotations

"""§31.4 Semantic validation — all 6 rejection/downgrade conditions.

The validator rejects or downgrades an assessment when:
1. extracted source evidence does not support the stated field;
2. a material calculation does not reproduce from supplied inputs;
3. a recommendation conflicts with a mandatory risk gate;
4. the output includes price targets, invented facts, or prohibited certainty;
5. the event is an amendment/cancellation but assessment refers to original terms;
6. the entity/facility relationship is not verified.
"""

import re
from dataclasses import dataclass
from typing import Any

# Price-target language and prohibited certainty — §31.4 condition 4
_PRICE_TARGET_PATTERNS = [
    re.compile(r"\bprice\s+target\b", re.IGNORECASE),
    re.compile(r"\btp\s*[=:]\s*\d", re.IGNORECASE),          # TP=500
    re.compile(r"\btarget\s+of\s+(?:rs\.?|inr)?\s*\d", re.IGNORECASE),
    re.compile(r"\bwill\s+(?:rise|fall|go\s+up|go\s+down|reach)\b", re.IGNORECASE),
    re.compile(r"\bstock\s+(?:will|is\s+going\s+to)\b", re.IGNORECASE),
    re.compile(r"\bexpect(?:ed|s)?\s+(?:the\s+)?(?:share|stock|price)\b", re.IGNORECASE),
    re.compile(r"\bguaranteed?\b", re.IGNORECASE),
    re.compile(r"\bcertain(?:ly)?\b", re.IGNORECASE),
]

# Amendment / cancellation event types — §31.4 condition 5
_AMENDMENT_EVENT_TYPES = frozenset({
    "ORDER_AMENDMENT", "ORDER_CANCELLATION", "TENDER_CANCELLED", "OUTLOOK_CHANGE",
})


@dataclass(frozen=True, slots=True)
class GroundingResult:
    is_verbatim: bool
    ungrounded_fields: list[str]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    semantic_valid: bool
    rejection_reasons: list[str]
    conditions_checked: list[str]
    hallucination_detected: bool = False


class SemanticValidator:
    """Deterministic validation enforcing §31.4 six rejection conditions."""

    # ---------------------------------------------------------------
    # Condition 1 helper: evidence must support each stated field
    # ---------------------------------------------------------------
    def verify_grounding(self, extracted_quote: str, raw_document_text: str) -> bool:
        """True if extracted_quote appears verbatim (whitespace-normalised) in raw text."""
        if not extracted_quote or not extracted_quote.strip():
            return False
        norm_quote = " ".join(extracted_quote.strip().split())
        norm_doc = " ".join(raw_document_text.split())
        return norm_quote in norm_doc

    def check_evidence_grounding(
        self,
        evidence_items: list[dict[str, Any]],
        raw_document_text: str,
    ) -> GroundingResult:
        """Condition 1: source evidence must support every stated field."""
        ungrounded: list[str] = []
        for item in evidence_items:
            text = item.get("text", "")
            field_name = item.get("field", "unknown")
            if text and not self.verify_grounding(text, raw_document_text):
                ungrounded.append(field_name)
        return GroundingResult(
            is_verbatim=len(ungrounded) == 0,
            ungrounded_fields=ungrounded,
        )

    # ---------------------------------------------------------------
    # Condition 2: material calculation must reproduce from inputs
    # ---------------------------------------------------------------
    def check_materiality_reproducible(
        self,
        value_inr_cr: float | None,
        ttm_revenue_inr: float | None,
        stated_materiality_ratio: float | None,
        tolerance: float = 0.01,
    ) -> tuple[bool, str]:
        """Condition 2: materiality_ratio = value / ttm_revenue must reproduce."""
        if value_inr_cr is None or ttm_revenue_inr is None or ttm_revenue_inr == 0:
            return True, ""  # null ratio is acceptable; §32.3 says null not zero
        if stated_materiality_ratio is None:
            return True, ""  # not claimed, no check needed
        computed = (value_inr_cr * 1e7) / ttm_revenue_inr  # cr to INR
        if abs(computed - stated_materiality_ratio) > tolerance:
            return False, (
                "Materiality ratio mismatch: stated="
                + str(stated_materiality_ratio)
                + " computed="
                + str(round(computed, 4))
            )
        return True, ""

    # ---------------------------------------------------------------
    # Condition 3: recommendation must not conflict with mandatory gates
    # ---------------------------------------------------------------
    def check_risk_gate_conflict(
        self,
        recommendation: str,
        firmness_level: int,
        entity_match_status: str,
        event_state: str,
        is_strategy_disabled: bool,
        event_type: str = "",
    ) -> tuple[bool, str]:
        """Condition 3: BUY_CANDIDATE conflicts with hard risk-gate failures."""
        neg_gov = {
            "NEGATIVE_GOVERNANCE",
            "AUDITOR_RESIGNATION",
            "CFO_RESIGNATION",
            "DEFAULT",
            "FORENSIC_ALLEGATION",
        }
        if (event_type in neg_gov or "NEGATIVE_GOVERNANCE" in event_type) and recommendation in ("BUY_CANDIDATE", "WATCH"):
            return False, f"Event type {event_type} conflicts with risk gate: NEGATIVE_GOVERNANCE cannot be {recommendation}"

        adverse_events = {
            "USFDA_WARNING_LETTER",
            "IMPORT_ALERT",
            "REGULATORY_ADVERSE_ACTION",
        }
        if event_type in adverse_events and recommendation == "BUY_CANDIDATE":
            return False, f"Event type {event_type} conflicts with risk gate: cannot be BUY_CANDIDATE"

        if recommendation != "BUY_CANDIDATE":
            return True, ""
        if firmness_level < 4:
            return False, (
                "BUY_CANDIDATE requires firmness level >= 4, got " + str(firmness_level)
            )
        if entity_match_status not in ("VERIFIED", "CONFIRMED"):
            return False, "BUY_CANDIDATE requires entity_match_status=VERIFIED"
        if is_strategy_disabled:
            return False, "BUY_CANDIDATE conflicts with disabled strategy gate"
        return True, ""

    # ---------------------------------------------------------------
    # Condition 4: no price targets, invented facts, prohibited certainty
    # ---------------------------------------------------------------
    def check_price_target_prohibition(
        self, rationale: str, invalidating_fact: str
    ) -> tuple[bool, str]:
        """Condition 4: output must not contain price targets or prohibited certainty."""
        combined = (rationale or "") + " " + (invalidating_fact or "")
        for pattern in _PRICE_TARGET_PATTERNS:
            if pattern.search(combined):
                return False, "Output contains prohibited price target or certainty claim"
        return True, ""

    # ---------------------------------------------------------------
    # Condition 5: amendment/cancellation must not reference original terms
    # ---------------------------------------------------------------
    def check_amendment_refers_to_original(
        self,
        event_type: str,
        rationale: str,
    ) -> tuple[bool, str]:
        """Condition 5: amendment events must not refer to original contract terms as if current."""
        if event_type not in _AMENDMENT_EVENT_TYPES:
            return True, ""
        original_term_phrases = [
            re.compile(r"\boriginal\s+contract\s+value\b", re.IGNORECASE),
            re.compile(r"\binitial\s+order\s+value\b", re.IGNORECASE),
            re.compile(r"\boriginal\s+terms?\s+(?:stand|apply|remain)\b", re.IGNORECASE),
        ]
        for p in original_term_phrases:
            if p.search(rationale or ""):
                return False, (
                    "Amendment event rationale references original terms as if current"
                )
        return True, ""

    # ---------------------------------------------------------------
    # Condition 6: entity/facility relationship must be verified
    # ---------------------------------------------------------------
    def check_entity_relationship_verified(
        self,
        issuer_match_status: str,
        entity_match_status: str,
    ) -> tuple[bool, str]:
        """Condition 6: entity/facility relationship must be verified before BUY_CANDIDATE."""
        unverified = []
        if issuer_match_status not in ("VERIFIED", "CONFIRMED"):
            unverified.append("issuer_match_status=" + issuer_match_status)
        if entity_match_status not in ("VERIFIED", "CONFIRMED"):
            unverified.append("entity_match_status=" + entity_match_status)
        if unverified:
            return False, "Entity relationship not verified: " + ", ".join(unverified)
        return True, ""

    # ---------------------------------------------------------------
    # Full validation — all 6 conditions
    # ---------------------------------------------------------------
    def validate_assessment(
        self,
        event: dict[str, Any] | None = None,
        assessment: Any = None,
        extracted_facts: list[dict[str, Any]] | None = None,
        raw_document_text: str = "",
        **kwargs: Any,
    ) -> ValidationResult:
        if assessment is not None:
            recommendation = getattr(assessment, "recommendation", "")
            rationale = getattr(assessment, "rationale", "")
            invalidating_fact = getattr(assessment, "invalidating_fact", "")
            facts = extracted_facts or []
            evidence_items = [
                {"field": str(item.get("field_name") or item.get("field") or "unknown"),
                 "text": str(item.get("evidence_text") or item.get("text") or "")}
                for item in facts
            ]
            event = event or {}
            result = self._validate_conditions(
                event=event,
                recommendation=str(recommendation),
                rationale=str(rationale),
                invalidating_fact=str(invalidating_fact),
                issuer_match_status=str(event.get("entity_match_status", "UNVERIFIED")),
                evidence_items=evidence_items,
                raw_document_text=raw_document_text,
            )
            halluc = any("ungrounded" in r.lower() or "invented" in r.lower() or "Condition 1" in r for r in result.rejection_reasons)
            return ValidationResult(
                is_valid=result.is_valid,
                semantic_valid=result.semantic_valid,
                rejection_reasons=result.rejection_reasons,
                conditions_checked=result.conditions_checked,
                hallucination_detected=halluc,
            )
        return self._validate_conditions(
            event=kwargs.get("event") or event or {},
            recommendation=str(kwargs["recommendation"]),
            rationale=str(kwargs["rationale"]),
            invalidating_fact=str(kwargs["invalidating_fact"]),
            issuer_match_status=str(kwargs.get("issuer_match_status", "UNVERIFIED")),
            evidence_items=list(kwargs.get("evidence_items") or []),
            raw_document_text=str(kwargs.get("raw_document_text") or raw_document_text),
            value_inr_cr=kwargs.get("value_inr_cr"),
            ttm_revenue_inr=kwargs.get("ttm_revenue_inr"),
            stated_materiality_ratio=kwargs.get("stated_materiality_ratio"),
            is_strategy_disabled=bool(kwargs.get("is_strategy_disabled", False)),
        )

    def _validate_conditions(
        self,
        *,
        event: dict[str, Any],
        recommendation: str,
        rationale: str,
        invalidating_fact: str,
        issuer_match_status: str,
        evidence_items: list[dict[str, Any]],
        raw_document_text: str,
        value_inr_cr: float | None = None,
        ttm_revenue_inr: float | None = None,
        stated_materiality_ratio: float | None = None,
        is_strategy_disabled: bool = False,
    ) -> ValidationResult:
        reasons: list[str] = []
        checked: list[str] = []

        # Condition 1
        checked.append("condition_1_evidence_grounding")
        grounding = self.check_evidence_grounding(evidence_items, raw_document_text)
        if not grounding.is_verbatim:
            reasons.append(
                "Condition 1: ungrounded evidence fields: "
                + ", ".join(grounding.ungrounded_fields)
            )

        # Condition 2
        checked.append("condition_2_calculation_reproducible")
        ok2, msg2 = self.check_materiality_reproducible(
            value_inr_cr, ttm_revenue_inr, stated_materiality_ratio
        )
        if not ok2:
            reasons.append("Condition 2: " + msg2)

        # Condition 3
        checked.append("condition_3_risk_gate_conflict")
        firmness = int(event.get("firmness_level", 0))
        entity_match = str(event.get("entity_match_status", "UNVERIFIED"))
        event_state = str(event.get("event_state", ""))
        event_type = str(event.get("event_type", ""))
        ok3, msg3 = self.check_risk_gate_conflict(
            recommendation, firmness, entity_match, event_state, is_strategy_disabled, event_type=event_type
        )
        if not ok3:
            reasons.append("Condition 3: " + msg3)

        # Condition 4
        checked.append("condition_4_price_target_prohibition")
        ok4, msg4 = self.check_price_target_prohibition(rationale, invalidating_fact)
        if not ok4:
            reasons.append("Condition 4: " + msg4)

        # Condition 5
        checked.append("condition_5_amendment_original_terms")
        event_type = str(event.get("event_type", ""))
        ok5, msg5 = self.check_amendment_refers_to_original(event_type, rationale)
        if not ok5:
            reasons.append("Condition 5: " + msg5)

        # Condition 6
        checked.append("condition_6_entity_relationship_verified")
        if recommendation == "BUY_CANDIDATE":
            ok6, msg6 = self.check_entity_relationship_verified(
                issuer_match_status, entity_match
            )
            if not ok6:
                reasons.append("Condition 6: " + msg6)

        is_valid = len(reasons) == 0
        return ValidationResult(
            is_valid=is_valid,
            semantic_valid=is_valid,
            rejection_reasons=reasons,
            conditions_checked=checked,
        )
