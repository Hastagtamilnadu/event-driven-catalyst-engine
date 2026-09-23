from __future__ import annotations

from enum import Enum, IntEnum


# ---------------------------------------------------------------------------
# §9.1 Primary event types — ALL 28 required names from the artifact.
# No deviation in name permitted.
# ---------------------------------------------------------------------------
class EventType(str, Enum):
    # Credit
    CREDIT_UPGRADE = "CREDIT_UPGRADE"
    CREDIT_DOWNGRADE = "CREDIT_DOWNGRADE"
    OUTLOOK_CHANGE = "OUTLOOK_CHANGE"
    # Tender / Order
    TENDER_L1 = "TENDER_L1"
    TENDER_AWARD = "TENDER_AWARD"
    LETTER_OF_AWARD = "LETTER_OF_AWARD"
    EXECUTED_CONTRACT = "EXECUTED_CONTRACT"
    TENDER_CANCELLED = "TENDER_CANCELLED"
    ORDER_WIN = "ORDER_WIN"
    ORDER_AMENDMENT = "ORDER_AMENDMENT"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    # Operational
    CAPACITY_COMMISSIONED = "CAPACITY_COMMISSIONED"
    REGULATORY_APPROVAL = "REGULATORY_APPROVAL"
    REGULATORY_ADVERSE_ACTION = "REGULATORY_ADVERSE_ACTION"
    # US FDA
    USFDA_OBSERVATION = "USFDA_OBSERVATION"
    USFDA_FINAL_CLASSIFICATION = "USFDA_FINAL_CLASSIFICATION"
    USFDA_WARNING_LETTER = "USFDA_WARNING_LETTER"
    IMPORT_ALERT = "IMPORT_ALERT"
    # Governance / adverse
    AUDITOR_RESIGNATION = "AUDITOR_RESIGNATION"
    CFO_RESIGNATION = "CFO_RESIGNATION"
    DEFAULT = "DEFAULT"
    FORENSIC_ALLEGATION = "FORENSIC_ALLEGATION"
    # Surveillance / market
    SURVEILLANCE_RESTRICTION = "SURVEILLANCE_RESTRICTION"
    PRICE_BAND_CHANGE = "PRICE_BAND_CHANGE"
    # Corporate events
    OWNERSHIP_TRANSACTION = "OWNERSHIP_TRANSACTION"
    IPO_LOCKIN = "IPO_LOCKIN"
    INDEX_REBALANCE = "INDEX_REBALANCE"
    POLICY_EVENT = "POLICY_EVENT"


# ---------------------------------------------------------------------------
# §9.2 Firmness ladder — exact levels 0–5
# The AI cannot promote a filing to a higher level. Level must come from
# deterministic fields and cited primary evidence.
# ---------------------------------------------------------------------------
class FirmnessLevel(IntEnum):
    RUMOUR = 0              # Rumour, media mention, unexplained claim — never paper
    INTENTION = 1           # MoU, exploration, non-binding intention — never paper
    L1_PREFERRED = 2        # L1/preferred bidder — evidence only
    AWARD_LOA = 3           # Award/LOA with entity and value — evidence only, pending manual
    BINDING_CONTRACT = 4    # Binding contract, counterparty, value, terms — eligible after all gates
    EXECUTION_EVIDENCE = 5  # Execution, invoice, milestone — credibility evidence


PAPER_ELIGIBLE_FIRMNESS_LEVELS: frozenset[int] = frozenset({4})


def is_paper_eligible_firmness(level: int) -> bool:
    """§9.2: Only level 4 is eligible for paper orders after all other gates."""
    return level in PAPER_ELIGIBLE_FIRMNESS_LEVELS


def ai_cannot_promote_firmness(
    deterministic_level: int,
    ai_proposed_level: int,
) -> int:
    """§9.2 guard: AI cannot promote a filing to a higher firmness level.
    Returns the deterministic_level unchanged if AI tries to go higher.
    """
    if ai_proposed_level > deterministic_level:
        return deterministic_level
    return ai_proposed_level


# ---------------------------------------------------------------------------
# §12 Decision state machine states — ALL 18 exact names from artifact.
# No renamed states permitted.
# ---------------------------------------------------------------------------
class EventState(str, Enum):
    INGESTED = "INGESTED"
    EXTRACTED = "EXTRACTED"
    ENTITY_VERIFIED = "ENTITY_VERIFIED"
    FACTS_VALIDATED = "FACTS_VALIDATED"
    AI_ASSESSED = "AI_ASSESSED"
    RISK_CHECKED = "RISK_CHECKED"
    PAPER_CANDIDATE = "PAPER_CANDIDATE"
    REVIEW_PENDING = "REVIEW_PENDING"
    APPROVED_PAPER_INTENT = "APPROVED_PAPER_INTENT"
    PAPER_ORDER_SENT = "PAPER_ORDER_SENT"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    POSITION_OPEN = "POSITION_OPEN"
    EXIT_REQUESTED = "EXIT_REQUESTED"
    POSITION_CLOSED = "POSITION_CLOSED"
    EXIT_UNFILLED = "EXIT_UNFILLED"


# ---------------------------------------------------------------------------
# §29.3 Parser quality states — exact names from artifact
# ---------------------------------------------------------------------------
class ParserQuality(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    OCR_REQUIRED = "OCR_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"
    MALICIOUS = "MALICIOUS"


# ---------------------------------------------------------------------------
# §10.1 Credibility flags — all 7 objective flags
# ---------------------------------------------------------------------------
class CredibilityFlag(str, Enum):
    PLEDGE_RISK = "PLEDGE_RISK"
    CASH_CONVERSION_RISK = "CASH_CONVERSION_RISK"
    RECEIVABLE_RISK = "RECEIVABLE_RISK"
    AUDITOR_EVENT = "AUDITOR_EVENT"
    RELATED_PARTY_RISK = "RELATED_PARTY_RISK"
    DILUTION_RISK = "DILUTION_RISK"
    DELIVERY_RISK = "DELIVERY_RISK"
    DEBT_REFINANCING_RISK = "DEBT_REFINANCING_RISK"
    VALUATION_STRETCH_RISK = "VALUATION_STRETCH_RISK"
    WORKING_CAPITAL_DRAG = "WORKING_CAPITAL_DRAG"
    DELEVERAGING_DISTRESS = "DELEVERAGING_DISTRESS"


# ---------------------------------------------------------------------------
# Remaining enums (unchanged in logic, preserved)
# ---------------------------------------------------------------------------
class SourceId(str, Enum):
    S1_EXCHANGE = "S1_EXCHANGE"
    S2_RATINGS = "S2_RATINGS"
    S3_TENDERS = "S3_TENDERS"
    S4_USFDA = "S4_USFDA"
    S5_PARIVESH = "S5_PARIVESH"
    S6_TRANSCRIPTS = "S6_TRANSCRIPTS"
    S7_OWNERSHIP = "S7_OWNERSHIP"
    S8_SURVEILLANCE = "S8_SURVEILLANCE"
    S9_CALENDAR = "S9_CALENDAR"


class Recommendation(str, Enum):
    BUY_CANDIDATE = "BUY_CANDIDATE"
    WATCH = "WATCH"
    PASS = "PASS"
    BLOCK = "BLOCK"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    MOO = "MOO"   # market-on-open (pre-open auction)
    MOC = "MOC"   # market-on-close


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXIT_UNFILLED = "EXIT_UNFILLED"
    INSUFFICIENT_INTRADAY_DATA = "INSUFFICIENT_INTRADAY_DATA"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXIT_REQUESTED = "EXIT_REQUESTED"
    EXIT_UNFILLED = "EXIT_UNFILLED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    OVERRIDE_TO_WATCH = "OVERRIDE_TO_WATCH"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"


class RelationshipType(str, Enum):
    SUBSIDIARY = "SUBSIDIARY"
    JOINT_VENTURE = "JOINT_VENTURE"
    ASSOCIATE = "ASSOCIATE"
    PARENT = "PARENT"
    PROMOTER_GROUP = "PROMOTER_GROUP"


class StrategyMode(str, Enum):
    DISABLED = "DISABLED"
    PAPER_ENABLED = "PAPER_ENABLED"
    ACTIVE_RISK_OVERLAY = "ACTIVE_RISK_OVERLAY"


class SourceMode(str, Enum):
    DISABLED = "DISABLED"
    PAPER_SIGNAL = "PAPER_SIGNAL"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    ACTIVE_RISK_OVERLAY = "ACTIVE_RISK_OVERLAY"


class IncidentSeverity(str, Enum):
    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


class FillReason(str, Enum):
    PRE_OPEN_AUCTION = "PRE_OPEN_AUCTION"
    INTRADAY_TRIGGER = "INTRADAY_TRIGGER"
    MARKET_OPEN = "MARKET_OPEN"
    STOP_HIT = "STOP_HIT"
    TARGET_HIT = "TARGET_HIT"
    TIME_STOP = "TIME_STOP"
    MANUAL = "MANUAL"
    INSUFFICIENT_INTRADAY_DATA = "INSUFFICIENT_INTRADAY_DATA"
