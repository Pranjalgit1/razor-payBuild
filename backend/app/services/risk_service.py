"""Application service that applies deterministic risk scores to cases."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import RecoveryCase, Transaction
from app.models.enums import FailureReason, SubscriptionStatus, TransactionStatus
from app.risk import RiskContext, RiskFactor, RiskResult, RuleBasedRiskEngine
from app.services.audit import record_action
from app.services.payment_service import count_recent_failures

_DEFAULT_ENGINE = RuleBasedRiskEngine()


def score_case(
    db: Session,
    case: RecoveryCase,
    *,
    engine: RuleBasedRiskEngine = _DEFAULT_ENGINE,
) -> RiskResult:
    """Persist an explainable score and append one idempotent audit entry."""
    if case.risk_score is not None and case.risk_level is not None:
        factors = tuple(
            RiskFactor(
                label=str(item["label"]),
                detail=str(item["detail"]),
                points=int(item["points"]),
            )
            for item in (case.risk_factors or [])
        )
        from app.models.enums import RiskLevel

        return RiskResult(
            score=case.risk_score,
            level=RiskLevel(case.risk_level),
            factors=factors,
        )

    transaction = case.transaction or db.get(Transaction, case.transaction_id)
    if transaction is None:
        raise ValueError("Recovery case transaction does not exist.")
    customer = case.customer or transaction.customer
    if customer is None:
        raise ValueError("Recovery case customer does not exist.")

    historical_statuses = (
        db.query(Transaction.status)
        .filter(
            Transaction.customer_id == customer.id,
            Transaction.is_historical.is_(True),
        )
        .all()
    )
    historical_failures = sum(
        1
        for (status,) in historical_statuses
        if status in (TransactionStatus.FAILED, TransactionStatus.ABANDONED)
    )

    try:
        failure_reason = (
            FailureReason(transaction.failure_reason)
            if transaction.failure_reason is not None
            else None
        )
    except ValueError:
        failure_reason = None

    result = engine.score(
        RiskContext(
            transaction_amount=transaction.amount,
            customer_lifetime_value=customer.lifetime_value,
            subscription_status=SubscriptionStatus(customer.subscription_status),
            previous_failures=count_recent_failures(
                db,
                customer.id,
                exclude_transaction_id=transaction.id,
            ),
            days_until_cancellation=customer.days_until_cancellation,
            failure_reason=failure_reason,
            historical_transactions=len(historical_statuses),
            historical_failures=historical_failures,
        )
    )

    case.risk_score = result.score
    case.risk_level = result.level.value
    case.risk_factors = [factor.as_dict() for factor in result.factors]
    record_action(
        db,
        case_id=case.id,
        action_type="risk_score_calculated",
        reasoning=(
            f"Deterministic rules calculated {result.level.value} risk "
            f"({result.score}/100)."
        ),
        details={
            "engine": "rule_based",
            "score": result.score,
            "risk_level": result.level.value,
            "factors": case.risk_factors,
        },
    )
    db.flush()
    return result
