"""Pydantic request/response schemas.

Every monetary field is an integer in **paise**. Responses additionally expose
a pre-formatted ``*_formatted`` string (for example ``"₹2,999"``) so the
frontend renders Indian-format currency without reimplementing the grouping
rules in TypeScript.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.agents.schemas import AgentDecision, Diagnosis
from app.models.enums import (
    ActionStatus,
    CaseStatus,
    CaseType,
    FailureReason,
    MessageChannel,
    MessageStatus,
    RecoveryAction,
    RiskLevel,
    SubscriptionStatus,
    TransactionStatus,
)
from app.services.formatting import format_inr


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


class CustomerBase(ORMModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = None
    lifetime_value: int = Field(default=0, ge=0, description="Paise")
    subscription_status: SubscriptionStatus = SubscriptionStatus.NONE
    days_until_cancellation: int | None = None
    is_business: bool = False


class CustomerCreate(CustomerBase):
    pass


class CustomerRead(CustomerBase):
    id: int
    created_at: datetime

    @computed_field
    @property
    def lifetime_value_formatted(self) -> str:
        return format_inr(self.lifetime_value)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


class TransactionRead(ORMModel):
    id: int
    customer_id: int
    amount: int = Field(description="Paise")
    currency: str
    status: TransactionStatus
    failure_reason: FailureReason | None = None
    attempt_number: int
    parent_transaction_id: int | None = None
    is_historical: bool
    created_at: datetime

    @computed_field
    @property
    def amount_formatted(self) -> str:
        return format_inr(self.amount)


class TransactionWithCustomer(TransactionRead):
    customer: CustomerRead


# ---------------------------------------------------------------------------
# Payment simulation
# ---------------------------------------------------------------------------


class PaymentSimulationRequest(BaseModel):
    """Create a simulated payment event.

    A failed payment (``succeed=False``) automatically opens a recovery case;
    a successful one does not.
    """

    customer_id: int
    amount: int = Field(gt=0, description="Paise. 299900 = INR 2,999")
    succeed: bool = False
    failure_reason: FailureReason | None = Field(
        default=FailureReason.EXPIRED_CARD,
        description="Required when succeed is false.",
    )
    case_type: CaseType = CaseType.FAILED_PAYMENT

    def resolved_failure_reason(self) -> FailureReason | None:
        if self.succeed:
            return None
        return self.failure_reason or FailureReason.EXPIRED_CARD


class PaymentSimulationResponse(BaseModel):
    transaction: TransactionRead
    recovery_case: "RecoveryCaseRead | None" = None
    message: str


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class AgentActionRead(ORMModel):
    id: int
    recovery_case_id: int
    action_type: str
    reasoning: str | None = None
    status: ActionStatus
    details: dict | None = None
    timestamp: datetime


class MessageRead(ORMModel):
    id: int
    recovery_case_id: int
    channel: MessageChannel
    recipient: str
    subject: str | None = None
    message: str
    status: MessageStatus
    timestamp: datetime


# ---------------------------------------------------------------------------
# Recovery cases
# ---------------------------------------------------------------------------


class RiskFactor(BaseModel):
    """One itemised contribution to the rule-based risk score."""

    label: str
    detail: str
    points: int


class RecoveryCaseRead(ORMModel):
    id: int
    transaction_id: int
    customer_id: int
    case_type: CaseType
    status: CaseStatus

    risk_score: int | None = Field(default=None, ge=0, le=100)
    risk_level: RiskLevel | None = None
    risk_factors: list[RiskFactor] | None = None

    diagnosis: Diagnosis | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    recommended_action: RecoveryAction | None = None
    decision_reason: str | None = None
    escalation_required: bool = False
    action_taken: RecoveryAction | None = None

    amount_at_risk: int
    amount_recovered: int

    retry_count: int
    reminder_count: int
    last_contact_at: datetime | None = None
    scheduled_retry_at: datetime | None = None

    created_at: datetime
    resolved_at: datetime | None = None

    @computed_field
    @property
    def amount_at_risk_formatted(self) -> str:
        return format_inr(self.amount_at_risk)

    @computed_field
    @property
    def amount_recovered_formatted(self) -> str:
        return format_inr(self.amount_recovered)


class RecoveryCaseListItem(RecoveryCaseRead):
    """Row shape for the Recovery Cases table."""

    customer: CustomerRead


class RecoveryCaseDetail(RecoveryCaseRead):
    """Full case view, including the chronological audit trail."""

    customer: CustomerRead
    transaction: TransactionRead
    actions: list[AgentActionRead] = Field(default_factory=list)
    messages: list[MessageRead] = Field(default_factory=list)


class AgentRunMetadataRead(BaseModel):
    provider: str
    configured_provider: str
    model: str | None = None
    request_id: str | None = None
    fallback_reason: str | None = None
    tool_calls: list[str] = Field(default_factory=list)


class RunAgentResponse(BaseModel):
    case: RecoveryCaseRead
    decision: AgentDecision
    metadata: AgentRunMetadataRead
    audit_actions: list[AgentActionRead] = Field(default_factory=list)
    idempotent: bool = False
    message: str


class RecoveryActionRequest(BaseModel):
    """Optional operator action; omitted means execute the agent recommendation."""

    action: RecoveryAction | None = None


class PolicyDecisionRead(BaseModel):
    allowed: bool
    code: str
    reason: str
    escalation_required: bool = False


class RecoveryActionResponse(BaseModel):
    case: RecoveryCaseRead
    policy: PolicyDecisionRead
    executed: bool
    audit_action: AgentActionRead
    details: dict = Field(default_factory=dict)
    message: str


class RecoveryPaymentRequest(BaseModel):
    """Simulate the customer's response after a recovery action."""

    amount: int | None = Field(default=None, gt=0, description="Paise; defaults to remaining amount")
    succeed: bool = True
    failure_reason: FailureReason | None = FailureReason.EXPIRED_CARD

    def resolved_failure_reason(self) -> FailureReason | None:
        if self.succeed:
            return None
        return self.failure_reason or FailureReason.EXPIRED_CARD


class RecoveryPaymentResponse(BaseModel):
    case: RecoveryCaseRead
    transaction: TransactionRead
    message: str


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------


class Page[T](BaseModel):
    """A page of results plus the total count for pagination controls."""

    items: list[T]
    total: int
    limit: int
    offset: int


class OperationResult(BaseModel):
    ok: bool = True
    message: str
    detail: dict | None = None


PaymentSimulationResponse.model_rebuild()
