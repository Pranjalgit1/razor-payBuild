"""Strict structured contracts shared by every recovery-agent provider."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from app.models.enums import (
    CaseStatus,
    CaseType,
    FailureReason,
    RecoveryAction,
    RiskLevel,
    SubscriptionStatus,
    TransactionStatus,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagnosis(StrEnum):
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
    MULTIPLE_FAILED_ATTEMPTS = "multiple_failed_attempts"
    UNKNOWN_FAILURE = "unknown_failure"


class AgentDecision(StrictModel):
    """The only write proposal an agent provider may return."""

    diagnosis: Diagnosis
    confidence: float = Field(ge=0, le=1, strict=True)
    recommended_action: RecoveryAction
    reason: StrictStr = Field(min_length=10, max_length=500)
    escalation_required: StrictBool


class AgentCaseContext(StrictModel):
    case_id: int
    customer_id: int
    transaction_id: int
    case_type: CaseType
    status: CaseStatus
    amount_at_risk: int = Field(ge=0)
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    risk_factors: list[dict]
    retry_count: int = Field(ge=0)
    reminder_count: int = Field(ge=0)
    has_scheduled_retry: bool
    policy_limits: dict[str, int]


class CustomerToolResult(StrictModel):
    id: int
    lifetime_value: int = Field(ge=0)
    subscription_status: SubscriptionStatus
    days_until_cancellation: int | None
    is_business: bool
    has_email: bool
    has_phone: bool


class TransactionToolResult(StrictModel):
    id: int
    customer_id: int
    amount: int = Field(gt=0)
    currency: str
    status: TransactionStatus
    failure_reason: FailureReason | None
    attempt_number: int = Field(ge=1)
    parent_transaction_id: int | None
    is_historical: bool


class PaymentHistoryToolInput(StrictModel):
    limit: int = Field(default=10, ge=1, le=20, strict=True)


class PaymentHistoryItem(TransactionToolResult):
    pass


class PaymentStatusToolResult(StrictModel):
    transaction_id: int
    status: TransactionStatus
    failure_reason: FailureReason | None
