"""SQLAlchemy ORM models.

Money convention: every monetary column stores **paise as an integer**
(1 INR = 100 paise). Integers avoid the floating-point drift that would
otherwise accumulate in recovered-revenue totals. Formatting to "₹2,999"
happens at the presentation layer, never in the database.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, UTCDateTime, timestamp_column
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


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)

    #: Total historical revenue from this customer, in paise.
    lifetime_value: Mapped[int] = mapped_column(Integer, default=0)
    subscription_status: Mapped[str] = mapped_column(
        String(32), default=SubscriptionStatus.NONE
    )
    #: Days remaining before an unpaid subscription is cancelled. Drives both
    #: the risk score and the urgency of the chosen intervention.
    days_until_cancellation: Mapped[int | None] = mapped_column(Integer, default=None)
    #: True for B2B accounts, which route to invoice-style recovery.
    is_business: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = timestamp_column()

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="Transaction.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<Customer {self.id} {self.name!r}>"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )

    #: Amount in paise.
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(32), default=TransactionStatus.PENDING)
    failure_reason: Mapped[str | None] = mapped_column(String(64), default=None)

    #: How many times this charge has already been attempted, including the
    #: original. The policy guard reads this to enforce the retry ceiling.
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    #: Set when a retry produces a new transaction, linking it to the original.
    parent_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), default=None
    )
    #: Marks rows loaded from a historical CSV so they can be excluded from
    #: live recovery workflows while still feeding analytics.
    is_historical: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = timestamp_column(index=True)

    customer: Mapped[Customer] = relationship(back_populates="transactions")
    recovery_case: Mapped["RecoveryCase | None"] = relationship(
        back_populates="transaction",
        uselist=False,
        foreign_keys="RecoveryCase.transaction_id",
    )

    __table_args__ = (Index("ix_transactions_status_created", "status", "created_at"),)

    @property
    def is_failed(self) -> bool:
        return self.status in (TransactionStatus.FAILED, TransactionStatus.ABANDONED)

    def __repr__(self) -> str:
        return f"<Transaction {self.id} {self.amount}p {self.status}>"


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )

    case_type: Mapped[str] = mapped_column(String(32), default=CaseType.FAILED_PAYMENT)
    status: Mapped[str] = mapped_column(
        String(32), default=CaseStatus.DETECTED, index=True
    )

    # --- Risk (deterministic, rule-based — populated in Phase 3) -----------
    risk_score: Mapped[int | None] = mapped_column(Integer, default=None)
    risk_level: Mapped[str | None] = mapped_column(String(16), default=None, index=True)
    #: Itemised factor contributions behind the score, surfaced in the UI so
    #: the number is explainable rather than opaque.
    risk_factors: Mapped[list | None] = mapped_column(default=None)

    # --- AI decision (populated in Phase 4) --------------------------------
    diagnosis: Mapped[str | None] = mapped_column(String(64), default=None)
    confidence: Mapped[float | None] = mapped_column(default=None)
    recommended_action: Mapped[str | None] = mapped_column(String(48), default=None)
    #: Concise, user-facing rationale. Never hidden chain-of-thought.
    decision_reason: Mapped[str | None] = mapped_column(Text, default=None)
    escalation_required: Mapped[bool] = mapped_column(default=False)
    #: The action the backend actually executed, which differs from
    #: recommended_action whenever the policy guard intervenes.
    action_taken: Mapped[str | None] = mapped_column(String(48), default=None)

    # --- Money (paise) ------------------------------------------------------
    amount_at_risk: Mapped[int] = mapped_column(Integer, default=0)
    amount_recovered: Mapped[int] = mapped_column(Integer, default=0)

    # --- Bounded-workflow counters (authoritative, enforced by backend) -----
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    created_at: Mapped[datetime] = timestamp_column(index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    transaction: Mapped[Transaction] = relationship(
        back_populates="recovery_case", foreign_keys=[transaction_id]
    )
    customer: Mapped[Customer] = relationship()
    actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="recovery_case",
        cascade="all, delete-orphan",
        order_by="AgentAction.timestamp",
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="recovery_case",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )

    @property
    def is_terminal(self) -> bool:
        from app.models.enums import TERMINAL_CASE_STATUSES

        return self.status in TERMINAL_CASE_STATUSES

    def __repr__(self) -> str:
        return f"<RecoveryCase {self.id} {self.status} risk={self.risk_score}>"


class AgentAction(Base):
    """The audit trail.

    One row per meaningful step in a case's life — detection, scoring,
    diagnosis, decision, execution, verification — including actions that were
    *blocked* by the policy guard, which are as important to record as the ones
    that ran.
    """

    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), index=True
    )

    action_type: Mapped[str] = mapped_column(String(48))
    #: Concise, user-facing explanation of why this step happened.
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16), default=ActionStatus.SUCCESS)
    #: Structured payload for the step (link URLs, retry schedule, blocked
    #: reason, and so on). Kept as JSON so the audit trail stays flexible.
    details: Mapped[dict | None] = mapped_column(default=None)

    timestamp: Mapped[datetime] = timestamp_column(index=True)

    recovery_case: Mapped[RecoveryCase] = relationship(back_populates="actions")

    def __repr__(self) -> str:
        return f"<AgentAction {self.id} {self.action_type} {self.status}>"


class Message(Base):
    """Customer communications sent during recovery (simulated in the demo)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), index=True
    )

    channel: Mapped[str] = mapped_column(String(16), default=MessageChannel.EMAIL)
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(300), default=None)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=MessageStatus.SENT)

    timestamp: Mapped[datetime] = timestamp_column(index=True)

    recovery_case: Mapped[RecoveryCase] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message {self.id} {self.channel} -> {self.recipient}>"


__all__ = [
    "Customer",
    "Transaction",
    "RecoveryCase",
    "AgentAction",
    "Message",
    "ActionStatus",
    "CaseStatus",
    "CaseType",
    "FailureReason",
    "MessageChannel",
    "MessageStatus",
    "RecoveryAction",
    "RiskLevel",
    "SubscriptionStatus",
    "TransactionStatus",
]
