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
        "L1_TENDER": EventType.EXECUTED_CONTRACT,
        "USFDA_APPROVAL": EventType.USFDA_FINAL_CLASSIFICATION,
        "USFDA_EIR": EventType.USFDA_FINAL_CLASSIFICATION,
        "USFDA_WARNING_LETTER": EventType.USFDA_WARNING_LETTER,
        "USFDA_483": EventType.USFDA_WARNING_LETTER,
        "ENVIRONMENTAL_CLEARANCE": EventType.ENVIRONMENTAL_CLEARANCE,
        "PARIVESH_EC": EventType.ENVIRONMENTAL_CLEARANCE,
        "CAPACITY_EXPANSION": EventType.CAPACITY_EXPANSION,
        "BOARD_MEETING": EventType.CALENDAR_EVENT,
        "AGM_EGM": EventType.CALENDAR_EVENT,
        "CALENDAR_EVENT": EventType.CALENDAR_EVENT,
        "SURVEILLANCE_ACTION": EventType.NEGATIVE_GOVERNANCE,
        "PROMOTER_PLEDGE": EventType.NEGATIVE_GOVERNANCE,
        "AUDITOR_RESIGNATION": EventType.NEGATIVE_GOVERNANCE,
        "NEGATIVE_GOVERNANCE": EventType.NEGATIVE_GOVERNANCE,
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
            return EventType.ENVIRONMENTAL_CLEARANCE
        if "RESIGNATION" in head_upper or "SURVEILLANCE" in head_upper or "SEBI" in head_upper:
            return EventType.NEGATIVE_GOVERNANCE

        return EventType.CALENDAR_EVENT
