"""Deterministic side effects for policy-approved recovery actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models.entities import Message, RecoveryCase, Transaction
from app.models.enums import (
    CaseStatus,
    MessageChannel,
    MessageStatus,
    RecoveryAction,
    TransactionStatus,
)


@dataclass(slots=True)
class ActionExecution:
    details: dict
    transaction: Transaction | None = None
    message: Message | None = None


def execute_action(
    db: Session,
    case: RecoveryCase,
    action: RecoveryAction,
    *,
    schedule_delay_hours: int = 24,
) -> ActionExecution:
    """Execute one already-approved action; the caller owns the transaction."""
    now = utcnow()
    case.status = CaseStatus.EXECUTING
    case.action_taken = action.value

    if action == RecoveryAction.RETRY_PAYMENT:
        retry = Transaction(
            customer_id=case.customer_id,
            amount=case.amount_at_risk - case.amount_recovered,
            currency=case.transaction.currency,
            status=TransactionStatus.PENDING,
            failure_reason=None,
            attempt_number=case.transaction.attempt_number + case.retry_count + 1,
            parent_transaction_id=case.transaction_id,
            is_historical=False,
        )
        db.add(retry)
        case.retry_count += 1
        case.scheduled_retry_at = None
        case.status = CaseStatus.VERIFYING
        db.flush()
        return ActionExecution(
            transaction=retry,
            details={
                "action": action.value,
                "retry_transaction_id": retry.id,
                "attempt_number": retry.attempt_number,
            },
        )

    if action == RecoveryAction.GENERATE_PAYMENT_LINK:
        case.status = CaseStatus.VERIFYING
        return ActionExecution(
            details={
                "action": action.value,
                "payment_link": _payment_link(case.id),
            }
        )

    if action in (RecoveryAction.SEND_EMAIL, RecoveryAction.SEND_WHATSAPP):
        channel = (
            MessageChannel.EMAIL
            if action == RecoveryAction.SEND_EMAIL
            else MessageChannel.WHATSAPP
        )
        recipient = case.customer.email if channel == MessageChannel.EMAIL else case.customer.phone
        if not recipient:
            raise ValueError(f"Customer has no {channel.value} recipient.")
        link = _payment_link(case.id)
        message = Message(
            recovery_case_id=case.id,
            channel=channel,
            recipient=recipient,
            subject=("Payment action required" if channel == MessageChannel.EMAIL else None),
            message=(
                f"Your payment of {case.amount_at_risk / 100:,.2f} INR needs attention. "
                f"Complete it securely at {link}"
            ),
            status=MessageStatus.SENT,
        )
        db.add(message)
        case.reminder_count += 1
        case.last_contact_at = now
        case.status = CaseStatus.VERIFYING
        db.flush()
        return ActionExecution(
            message=message,
            details={
                "action": action.value,
                "channel": channel.value,
                "message_id": message.id,
                "recipient": recipient,
                "payment_link": link,
            },
        )

    if action == RecoveryAction.SCHEDULE_RETRY:
        scheduled_for = now + timedelta(hours=schedule_delay_hours)
        case.scheduled_retry_at = scheduled_for
        case.status = CaseStatus.EXECUTING
        return ActionExecution(
            details={
                "action": action.value,
                "scheduled_for": scheduled_for.isoformat().replace("+00:00", "Z"),
            }
        )

    if action == RecoveryAction.ESCALATE_TO_HUMAN:
        case.status = CaseStatus.ESCALATED
        case.escalation_required = True
        return ActionExecution(
            details={"action": action.value, "queue": "human_recovery_review"}
        )

    raise ValueError(f"Unsupported recovery action: {action.value}")


def _payment_link(case_id: int) -> str:
    return f"https://pay.razorpay.local/recovery/{case_id}"
