from __future__ import annotations

"""§12 Decision State Machine — exact artifact state names.

Artifact §12 verbatim:
  INGESTED -> EXTRACTED -> ENTITY_VERIFIED -> FACTS_VALIDATED
           -> AI_ASSESSED -> RISK_CHECKED -> PAPER_CANDIDATE
           -> REVIEW_PENDING -> APPROVED_PAPER_INTENT
           -> PAPER_ORDER_SENT -> PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED
           -> POSITION_OPEN -> EXIT_REQUESTED -> POSITION_CLOSED | EXIT_UNFILLED

Invalid, stale, amended, duplicate, unsupported, or unresolved events enter
a terminal non-trading state with a reason. The event ID and unique
paper-order client ID make every transition idempotent.
"""

from qual_event_engine.domain.enums import EventState

# ---------------------------------------------------------------------------
# Alias for backwards compatibility — callers using EventState directly
# ---------------------------------------------------------------------------
DecisionState = EventState

# ---------------------------------------------------------------------------
# §12 valid transitions — exact artifact DAG
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[EventState, frozenset[EventState]] = {
    EventState.INGESTED: frozenset({
        EventState.EXTRACTED,
        EventState.REJECTED,    # invalid/duplicate/unsupported/unresolved
    }),
    EventState.EXTRACTED: frozenset({
        EventState.ENTITY_VERIFIED,
        EventState.REJECTED,
    }),
    EventState.ENTITY_VERIFIED: frozenset({
        EventState.FACTS_VALIDATED,
        EventState.REJECTED,
    }),
    EventState.FACTS_VALIDATED: frozenset({
        EventState.AI_ASSESSED,
        EventState.REJECTED,
    }),
    EventState.AI_ASSESSED: frozenset({
        EventState.RISK_CHECKED,
        EventState.REJECTED,
    }),
    EventState.RISK_CHECKED: frozenset({
        EventState.PAPER_CANDIDATE,
        EventState.REJECTED,
    }),
    EventState.PAPER_CANDIDATE: frozenset({
        EventState.REVIEW_PENDING,
        EventState.REJECTED,
    }),
    EventState.REVIEW_PENDING: frozenset({
        EventState.APPROVED_PAPER_INTENT,
        EventState.REJECTED,
    }),
    EventState.APPROVED_PAPER_INTENT: frozenset({
        EventState.PAPER_ORDER_SENT,
        EventState.CANCELLED,
    }),
    EventState.PAPER_ORDER_SENT: frozenset({
        EventState.PARTIALLY_FILLED,
        EventState.FILLED,
        EventState.CANCELLED,
        EventState.REJECTED,
    }),
    EventState.PARTIALLY_FILLED: frozenset({
        EventState.PARTIALLY_FILLED,   # further partial fills
        EventState.FILLED,
        EventState.CANCELLED,
        EventState.POSITION_OPEN,
    }),
    EventState.FILLED: frozenset({
        EventState.POSITION_OPEN,
    }),
    EventState.CANCELLED: frozenset(),   # terminal
    EventState.REJECTED: frozenset(),    # terminal
    EventState.POSITION_OPEN: frozenset({
        EventState.EXIT_REQUESTED,      # §12: only path out of POSITION_OPEN
    }),
    EventState.EXIT_REQUESTED: frozenset({
        EventState.POSITION_CLOSED,
        EventState.EXIT_UNFILLED,
    }),
    EventState.POSITION_CLOSED: frozenset(),  # terminal
    EventState.EXIT_UNFILLED: frozenset(),    # terminal — §15.4 / §32.6
}

# Terminal states — no further transitions allowed
TERMINAL_STATES: frozenset[EventState] = frozenset({
    EventState.CANCELLED,
    EventState.REJECTED,
    EventState.POSITION_CLOSED,
    EventState.EXIT_UNFILLED,
})


class DecisionStateMachine:
    """State machine governing the deterministic progression of events.

    All state names are the exact §12 artifact names from EventState.
    Illegal transitions raise ValueError. Idempotency is the caller's
    responsibility (event_id + client_order_id uniqueness).
    """

    def __init__(self, initial_state: EventState = EventState.INGESTED) -> None:
        self.state = initial_state

    def can_transition_to(self, target: EventState) -> bool:
        return target in VALID_TRANSITIONS.get(self.state, frozenset())

    def transition(self, target: EventState, reason: str = "") -> None:
        if not self.can_transition_to(target):
            raise ValueError(
                "Illegal state transition from "
                + self.state.value
                + " to "
                + target.value
                + ((" — " + reason) if reason else "")
            )
        self.state = target

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def is_paper_active(self) -> bool:
        """True when a paper position is open or an exit is pending."""
        return self.state in (
            EventState.POSITION_OPEN,
            EventState.EXIT_REQUESTED,
        )
