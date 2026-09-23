from __future__ import annotations

from typing import ClassVar

from qual_event_engine.domain.enums import EventType


class EventTaxonomy:
    """Classifies raw incoming source categories and headlines into canonical event taxonomy."""

    MAPPINGS: ClassVar[dict[str, EventType]] = {
        "RATING_UPGRADE": EventType.CREDIT_UPGRADE,
        "CREDIT_UPGRADE": EventType.CREDIT_UPGRADE,
        "ORDER_WIN": EventType.ORDER_WIN,
        "NEW_ORDER": EventType.ORDER_WIN,
        "CONTRACT_AWARD": EventType.ORDER_WIN,
        "TENDER_WIN": EventType.EXECUTED_CONTRACT,
        "EXECUTED_CONTRACT": EventType.EXECUTED_CONTRACT,
        "L1_TENDER": EventType.TENDER_L1,
        "USFDA_APPROVAL": EventType.USFDA_FINAL_CLASSIFICATION,
        "USFDA_EIR": EventType.USFDA_FINAL_CLASSIFICATION,
        "USFDA_WARNING_LETTER": EventType.USFDA_WARNING_LETTER,
        "USFDA_483": EventType.USFDA_OBSERVATION,
        "ENVIRONMENTAL_CLEARANCE": EventType.REGULATORY_APPROVAL,
        "PARIVESH_EC": EventType.REGULATORY_APPROVAL,
        "CAPACITY_EXPANSION": EventType.CAPACITY_COMMISSIONED,
        "BOARD_MEETING": EventType.POLICY_EVENT,
        "AGM_EGM": EventType.POLICY_EVENT,
        "CALENDAR_EVENT": EventType.POLICY_EVENT,
        "SURVEILLANCE_ACTION": EventType.SURVEILLANCE_RESTRICTION,
        "PROMOTER_PLEDGE": EventType.SURVEILLANCE_RESTRICTION,
        "AUDITOR_RESIGNATION": EventType.AUDITOR_RESIGNATION,
        "NEGATIVE_GOVERNANCE": EventType.FORENSIC_ALLEGATION,
    }

    @classmethod
    def classify(cls, raw_type: str, headline: str = "") -> EventType:
        norm = raw_type.upper().replace(" ", "_")
        if norm in cls.MAPPINGS:
            return cls.MAPPINGS[norm]

        head_upper = headline.upper()
        if "UPGRADE" in head_upper and "RATING" in head_upper:
            return EventType.CREDIT_UPGRADE
        if "ORDER" in head_upper or "BAGS" in head_upper or "AWARDED" in head_upper:
            return EventType.ORDER_WIN
        if "USFDA" in head_upper or "FDA" in head_upper:
            if "WARNING" in head_upper or "483" in head_upper:
                return EventType.USFDA_WARNING_LETTER
            return EventType.USFDA_FINAL_CLASSIFICATION
        if "ENVIRONMENTAL CLEARANCE" in head_upper or "PARIVESH" in head_upper:
            return EventType.REGULATORY_APPROVAL
        if "RESIGNATION" in head_upper:
            return EventType.AUDITOR_RESIGNATION
        if "SURVEILLANCE" in head_upper:
            return EventType.SURVEILLANCE_RESTRICTION
        if "SEBI" in head_upper:
            return EventType.FORENSIC_ALLEGATION

        return EventType.POLICY_EVENT
