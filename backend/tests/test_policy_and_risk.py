"""Boundary checks for deterministic risk and backend policy limits."""

from __future__ import annotations

from app.config import Settings
from app.models.entities import Customer, RecoveryCase, Transaction
from app.models.enums import (
    CaseStatus,
    FailureReason,
    RecoveryAction,
    SubscriptionStatus,
    TransactionStatus,
)
from app.risk import RiskContext, RuleBasedRiskEngine, risk_level_for_score
from app.workflow.policy_guard import validate_action


def _case(*, retry_count: int = 0, reminder_count: int = 0) -> RecoveryCase:
    customer = Customer(
        id=1,
        name="Boundary Customer",
        email="boundary@example.com",
        lifetime_value=100_000,
        subscription_status=SubscriptionStatus.NONE,
    )
    transaction = Transaction(
        id=1,
        customer_id=1,
        amount=100_000,
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.NETWORK_ERROR,
    )
    case = RecoveryCase(
        id=1,
        transaction_id=1,
        customer_id=1,
        status=CaseStatus.DETECTED,
        risk_score=50,
        risk_level="medium",
        amount_at_risk=100_000,
        retry_count=retry_count,
        reminder_count=reminder_count,
    )
    case.customer = customer
    case.transaction = transaction
    return case


def test_risk_bands_use_exact_prd_boundaries():
    expected = {
        0: "low",
        30: "low",
        31: "medium",
        60: "medium",
        61: "high",
        80: "high",
        81: "critical",
        100: "critical",
    }
    assert {score: risk_level_for_score(score).value for score in expected} == expected


def test_maximum_risk_factors_reconcile_to_public_score():
    result = RuleBasedRiskEngine().score(
        RiskContext(
            transaction_amount=10_000_000,
            customer_lifetime_value=10_000_000,
            subscription_status=SubscriptionStatus.PAST_DUE,
            previous_failures=10,
            days_until_cancellation=0,
            failure_reason=FailureReason.MANDATE_REVOKED,
            historical_transactions=10,
            historical_failures=10,
        )
    )
    assert result.score == 100
    assert sum(factor.points for factor in result.factors) == result.score


def test_retry_and_reminder_limits_are_hard_boundaries():
    policy = Settings(max_payment_retries=2, max_reminders=3)

    retry = validate_action(
        _case(retry_count=2),
        RecoveryAction.RETRY_PAYMENT,
        policy=policy,
    )
    assert retry.allowed is False
    assert retry.code == "retry_limit_reached"
    assert retry.escalation_required is True

    reminder = validate_action(
        _case(reminder_count=3),
        RecoveryAction.SEND_EMAIL,
        policy=policy,
    )
    assert reminder.allowed is False
    assert reminder.code == "reminder_limit_reached"
    assert reminder.escalation_required is True
