"""Recovery case service — detection and case lifecycle.

This is the DETECT stage of the loop. When a payment event indicates revenue is
at risk, a recovery case is opened here and the first audit-trail entry is
written. Diagnosis, decision and execution are layered on in later phases.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import RecoveryCase, Transaction
from app.models.enums import CaseStatus, CaseType, FailureReason
from app.services.audit import record_action
from app.services.formatting import format_inr

#: Which revenue-risk scenario a given failure reason belongs to. Keeps the
#: four PRD scenarios flowing through one pipeline instead of four.
_CASE_TYPE_BY_REASON: dict[FailureReason, CaseType] = {
    FailureReason.CHECKOUT_ABANDONED: CaseType.CHECKOUT_ABANDONMENT,
    FailureReason.INVOICE_OVERDUE: CaseType.OVERDUE_INVOICE,
    FailureReason.MANDATE_REVOKED: CaseType.FAILED_SUBSCRIPTION,
}


def classify_case_type(transaction: Transaction) -> CaseType:
    """Infer the scenario from the transaction and the customer it belongs to."""
    reason = transaction.failure_reason
    if reason:
        mapped = _CASE_TYPE_BY_REASON.get(FailureReason(reason))
        if mapped:
            return mapped

    # A business account failing a charge is receivables, not a card problem.
    if transaction.customer and transaction.customer.is_business:
        return CaseType.OVERDUE_INVOICE

    from app.models.enums import SubscriptionStatus

    if (
        transaction.customer
        and transaction.customer.subscription_status == SubscriptionStatus.ACTIVE
    ):
        return CaseType.FAILED_SUBSCRIPTION

    return CaseType.FAILED_PAYMENT


def detect_revenue_at_risk(db: Session, transaction: Transaction) -> RecoveryCase | None:
    """Open a recovery case for a failed transaction.

    Returns ``None`` when there is nothing to recover — a successful payment —
    or when a case already exists for this transaction, which keeps the
    endpoint idempotent under repeated calls.
    """
    if not transaction.is_failed:
        return None

    existing = (
        db.query(RecoveryCase)
        .filter(RecoveryCase.transaction_id == transaction.id)
        .one_or_none()
    )
    if existing is not None:
        return existing

    case = RecoveryCase(
        transaction_id=transaction.id,
        customer_id=transaction.customer_id,
        case_type=classify_case_type(transaction),
        status=CaseStatus.DETECTED,
        amount_at_risk=transaction.amount,
        amount_recovered=0,
    )
    db.add(case)
    db.flush()

    reason = transaction.failure_reason or "unknown"
    record_action(
        db,
        case_id=case.id,
        action_type="revenue_at_risk_detected",
        reasoning=(
            f"Payment of {format_inr(transaction.amount)} failed "
            f"({reason.replace('_', ' ')}). Revenue at risk."
        ),
        details={
            "transaction_id": transaction.id,
            "amount_at_risk": transaction.amount,
            "failure_reason": reason,
            "case_type": case.case_type,
        },
    )
    return case


def get_case(db: Session, case_id: int) -> RecoveryCase | None:
    return db.get(RecoveryCase, case_id)
