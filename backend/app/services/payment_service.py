"""Payment service — the simulated payment gateway.

The demo runs against a deterministic simulator rather than a live gateway, but
the interface is the one a real integration would expose, so swapping in Stripe
test mode or Razorpay later means replacing this module and nothing else.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Customer, Transaction
from app.models.enums import FailureReason, TransactionStatus


class PaymentError(Exception):
    """Raised when a payment operation cannot be performed at all."""


def create_payment(
    db: Session,
    *,
    customer: Customer,
    amount: int,
    succeed: bool,
    failure_reason: FailureReason | None = None,
    attempt_number: int = 1,
    parent_transaction_id: int | None = None,
    currency: str = "INR",
) -> Transaction:
    """Record a payment attempt and its outcome.

    ``amount`` is in paise. A failed attempt stores the reason it failed; a
    successful one never carries a failure reason.
    """
    if amount <= 0:
        raise PaymentError("Payment amount must be greater than zero.")

    if succeed:
        status = TransactionStatus.SUCCESS
        reason = None
    else:
        reason = failure_reason or FailureReason.EXPIRED_CARD
        status = (
            TransactionStatus.ABANDONED
            if reason is FailureReason.CHECKOUT_ABANDONED
            else TransactionStatus.FAILED
        )

    transaction = Transaction(
        customer_id=customer.id,
        amount=amount,
        currency=currency,
        status=status,
        failure_reason=reason.value if reason else None,
        attempt_number=attempt_number,
        parent_transaction_id=parent_transaction_id,
    )
    db.add(transaction)
    db.flush()
    return transaction


def complete_pending_payment(
    db: Session,
    transaction: Transaction,
    *,
    succeed: bool,
    failure_reason: FailureReason | None = None,
) -> Transaction:
    """Apply a simulated gateway outcome to an existing pending attempt."""
    if transaction.status != TransactionStatus.PENDING:
        raise PaymentError("Only a pending payment attempt can be completed.")
    if succeed:
        transaction.status = TransactionStatus.SUCCESS
        transaction.failure_reason = None
    else:
        reason = failure_reason or FailureReason.EXPIRED_CARD
        transaction.status = (
            TransactionStatus.ABANDONED
            if reason == FailureReason.CHECKOUT_ABANDONED
            else TransactionStatus.FAILED
        )
        transaction.failure_reason = reason.value
    db.flush()
    return transaction


def count_recent_failures(
    db: Session,
    customer_id: int,
    *,
    limit: int = 10,
    exclude_transaction_id: int | None = None,
) -> int:
    """How many of a customer's recent live transactions failed.

    Historical imports are excluded so a bulk CSV load cannot distort live
    scoring. The current recovery transaction can also be excluded so the
    factor means *previous* failures rather than including the triggering one.
    """
    query = db.query(Transaction.status).filter(
        Transaction.customer_id == customer_id,
        Transaction.is_historical.is_(False),
    )
    if exclude_transaction_id is not None:
        query = query.filter(Transaction.id != exclude_transaction_id)

    rows = (
        query.order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )
    return sum(
        1
        for (status,) in rows
        if status in (TransactionStatus.FAILED, TransactionStatus.ABANDONED)
    )


def get_payment_history(
    db: Session, customer_id: int, *, limit: int = 20
) -> list[Transaction]:
    """A customer's recent transactions, newest first.

    Exposed to the AI agent in Phase 4 as the ``get_payment_history`` tool —
    which is why it returns a bounded list rather than an open query.
    """
    return (
        db.query(Transaction)
        .filter(Transaction.customer_id == customer_id)
        .order_by(Transaction.created_at.desc())
        .limit(limit)
        .all()
    )
