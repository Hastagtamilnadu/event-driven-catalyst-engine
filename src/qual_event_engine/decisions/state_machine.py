from __future__ import annotations

from enum import Enum


class DecisionState(str, Enum):
    INGESTED = "INGESTED"
    FACTS_EXTRACTED = "FACTS_EXTRACTED"
    FACTS_GROUNDED = "FACTS_GROUNDED"
    GROUNDING_FAILED = "GROUNDING_FAILED"
    ASSESSED = "ASSESSED"
    RISK_CHECKED = "RISK_CHECKED"
    RISK_BLOCKED = "RISK_BLOCKED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    PAPER_ORDER_CREATED = "PAPER_ORDER_CREATED"
    REJECTED = "REJECTED"


VALID_TRANSITIONS: dict[DecisionState, set[DecisionState]] = {
    DecisionState.INGESTED: {DecisionState.FACTS_EXTRACTED, DecisionState.REJECTED},
    DecisionState.FACTS_EXTRACTED: {DecisionState.FACTS_GROUNDED, DecisionState.GROUNDING_FAILED},
    DecisionState.FACTS_GROUNDED: {DecisionState.ASSESSED, DecisionState.REJECTED},
    DecisionState.GROUNDING_FAILED: {DecisionState.REJECTED},
    DecisionState.ASSESSED: {DecisionState.RISK_CHECKED, DecisionState.REJECTED},
    DecisionState.RISK_CHECKED: {DecisionState.PENDING_HUMAN_REVIEW, DecisionState.APPROVED_FOR_PAPER, DecisionState.RISK_BLOCKED},
    DecisionState.RISK_BLOCKED: {DecisionState.REJECTED},
    DecisionState.PENDING_HUMAN_REVIEW: {DecisionState.APPROVED_FOR_PAPER, DecisionState.REJECTED},
    DecisionState.APPROVED_FOR_PAPER: {DecisionState.PAPER_ORDER_CREATED},
    DecisionState.PAPER_ORDER_CREATED: set(),
    DecisionState.REJECTED: set(),
}


class DecisionStateMachine:
    """State machine governing the deterministic progression of events to paper trading."""

    def __init__(self, initial_state: DecisionState = DecisionState.INGESTED) -> None:
        self.state = initial_state

    def can_transition_to(self, target: DecisionState) -> bool:
        return target in VALID_TRANSITIONS.get(self.state, set())

    def transition(self, target: DecisionState) -> None:
        if not self.can_transition_to(target):
            raise ValueError(f"Illegal transition from {self.state} to {target}")
        self.state = target
