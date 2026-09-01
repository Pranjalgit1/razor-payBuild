"""Domain enumerations shared across models, schemas and services.

These are stored as plain strings in the database rather than native enum
columns, which keeps the schema portable between PostgreSQL and SQLite and
avoids a migration every time a value is added.
"""

from __future__ import annotations

from enum import StrEnum


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    NONE = "none"


class TransactionStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    ABANDONED = "abandoned"


class FailureReason(StrEnum):
    """Why a payment did not complete.

    The first group are true payment failures; the last two model the
    non-payment revenue-risk scenarios so they flow through the same pipeline.
    """

    EXPIRED_CARD = "expired_card"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    TEMPORARY_BANK_FAILURE = "temporary_bank_failure"
    CARD_DECLINED = "card_declined"
    NETWORK_ERROR = "network_error"
    AUTHENTICATION_FAILURE = "authentication_failure"
    INVALID_CARD = "invalid_card"
    MANDATE_REVOKED = "mandate_revoked"
    CHECKOUT_ABANDONED = "checkout_abandoned"
    INVOICE_OVERDUE = "invoice_overdue"


#: Failure reasons where re-presenting the same instrument has a real chance of
#: succeeding. Used by the risk engine (Phase 3) and the policy guard (Phase 5).
RETRYABLE_FAILURE_REASONS: frozenset[FailureReason] = frozenset(
    {
        FailureReason.INSUFFICIENT_FUNDS,
        FailureReason.TEMPORARY_BANK_FAILURE,
        FailureReason.NETWORK_ERROR,
        FailureReason.CARD_DECLINED,
    }
)


class CaseType(StrEnum):
    """Which revenue-risk scenario produced the case."""

    FAILED_PAYMENT = "failed_payment"
    CHECKOUT_ABANDONMENT = "checkout_abandonment"
    FAILED_SUBSCRIPTION = "failed_subscription"
    OVERDUE_INVOICE = "overdue_invoice"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CaseStatus(StrEnum):
    """Recovery case lifecycle.

    Mirrors the DETECT → DIAGNOSE → DECIDE → ACT → VERIFY → RECOVER loop, plus
    the terminal states a case can settle into.
    """

    DETECTED = "detected"
    DIAGNOSED = "diagnosed"
    DECIDED = "decided"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERED = "recovered"
    ESCALATED = "escalated"
    FAILED = "failed"
    ABANDONED = "abandoned"


#: Cases in these states are finished — no further agent work should occur.
TERMINAL_CASE_STATUSES: frozenset[CaseStatus] = frozenset(
    {CaseStatus.RECOVERED, CaseStatus.FAILED, CaseStatus.ABANDONED}
)


class RecoveryAction(StrEnum):
    """The controlled action set.

    The AI agent selects one of these; the backend executes it only after the
    policy guard approves. The agent never performs a side effect directly.
    """

    RETRY_PAYMENT = "retry_payment"
    GENERATE_PAYMENT_LINK = "generate_payment_link"
    SEND_EMAIL = "send_email"
    SEND_WHATSAPP = "send_whatsapp"
    SCHEDULE_RETRY = "schedule_retry"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    MARK_CASE_RESOLVED = "mark_case_resolved"


class ActionStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    #: The AI proposed this action and the policy guard refused it.
    BLOCKED = "blocked"


class MessageChannel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
