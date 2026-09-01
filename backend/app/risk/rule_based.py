"""Transparent deterministic risk scoring used by the MVP."""

from __future__ import annotations

from app.models.enums import FailureReason, RiskLevel, SubscriptionStatus
from app.risk.base import RiskContext, RiskFactor, RiskResult


class RuleBasedRiskEngine:
    """Score revenue urgency from seven fixed, itemised factors.

    Contributions are intentionally simple and stable. The raw score is
    clamped to 100 so adding multiple severe signals can never exceed the
    public 0-100 contract.
    """

    def score(self, context: RiskContext) -> RiskResult:
        factors = (
            self._transaction_amount(context.transaction_amount),
            self._lifetime_value(context.customer_lifetime_value),
            self._subscription(context.subscription_status),
            self._previous_failures(context.previous_failures),
            self._cancellation_urgency(context.days_until_cancellation),
            self._failure_type(context.failure_reason),
            self._customer_history(
                context.historical_transactions, context.historical_failures
            ),
        )
        score = max(0, min(100, sum(factor.points for factor in factors)))
        return RiskResult(score=score, level=risk_level_for_score(score), factors=factors)

    @staticmethod
    def _transaction_amount(amount: int) -> RiskFactor:
        if amount >= 5_000_000:
            points = 20
        elif amount >= 1_000_000:
            points = 14
        elif amount >= 250_000:
            points = 8
        else:
            points = 3
        return RiskFactor("Transaction amount", f"{amount} paise at risk", points)

    @staticmethod
    def _lifetime_value(ltv: int) -> RiskFactor:
        if ltv >= 5_000_000:
            points = 20
        elif ltv >= 2_000_000:
            points = 13
        elif ltv >= 500_000:
            points = 7
        else:
            points = 3
        return RiskFactor("Customer lifetime value", f"{ltv} paise lifetime value", points)

    @staticmethod
    def _subscription(status: SubscriptionStatus) -> RiskFactor:
        points_by_status = {
            SubscriptionStatus.PAST_DUE: 12,
            SubscriptionStatus.ACTIVE: 10,
            SubscriptionStatus.PAUSED: 6,
            SubscriptionStatus.CANCELLED: 2,
            SubscriptionStatus.NONE: 0,
        }
        return RiskFactor(
            "Subscription status",
            f"Customer subscription is {status.value.replace('_', ' ')}",
            points_by_status[status],
        )

    @staticmethod
    def _previous_failures(count: int) -> RiskFactor:
        points = 0 if count == 0 else 5 if count == 1 else 10 if count == 2 else 14
        return RiskFactor(
            "Previous payment failures",
            f"{count} previous live failure{'s' if count != 1 else ''}",
            points,
        )

    @staticmethod
    def _cancellation_urgency(days: int | None) -> RiskFactor:
        if days is None:
            points = 0
            detail = "No cancellation deadline"
        elif days <= 1:
            points = 12
            detail = f"Cancellation in {days} day"
        elif days <= 3:
            points = 10
            detail = f"Cancellation in {days} days"
        elif days <= 7:
            points = 8
            detail = f"Cancellation in {days} days"
        elif days <= 14:
            points = 4
            detail = f"Cancellation in {days} days"
        else:
            points = 1
            detail = f"Cancellation in {days} days"
        return RiskFactor("Cancellation urgency", detail, points)

    @staticmethod
    def _failure_type(reason: FailureReason | None) -> RiskFactor:
        points_by_reason = {
            FailureReason.MANDATE_REVOKED: 15,
            FailureReason.INVOICE_OVERDUE: 14,
            FailureReason.EXPIRED_CARD: 12,
            FailureReason.INVALID_CARD: 12,
            FailureReason.AUTHENTICATION_FAILURE: 11,
            FailureReason.CHECKOUT_ABANDONED: 10,
            FailureReason.INSUFFICIENT_FUNDS: 8,
            FailureReason.CARD_DECLINED: 8,
            FailureReason.TEMPORARY_BANK_FAILURE: 4,
            FailureReason.NETWORK_ERROR: 4,
        }
        points = points_by_reason.get(reason, 5)
        detail = (
            reason.value.replace("_", " ") if reason is not None else "Unknown failure"
        )
        return RiskFactor("Payment failure type", detail, points)

    @staticmethod
    def _customer_history(total: int, failures: int) -> RiskFactor:
        if total <= 0:
            return RiskFactor("Customer history", "No historical payments", 5)
        failure_rate = failures / total
        if failure_rate >= 0.5:
            points = 7
        elif failure_rate >= 0.25:
            points = 5
        elif failures > 0:
            points = 2
        else:
            points = 0
        return RiskFactor(
            "Customer history",
            f"{failures} failures across {total} historical payments",
            points,
        )


def risk_level_for_score(score: int) -> RiskLevel:
    """Map the public 0-100 score to the exact PRD risk bands."""
    if not 0 <= score <= 100:
        raise ValueError("Risk score must be between 0 and 100.")
    if score <= 30:
        return RiskLevel.LOW
    if score <= 60:
        return RiskLevel.MEDIUM
    if score <= 80:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL
