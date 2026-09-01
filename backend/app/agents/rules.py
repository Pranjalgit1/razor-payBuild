"""Deterministic recovery-decision provider used for offline demos and fallback."""

from __future__ import annotations

from app.agents.base import AgentProviderResult, AgentRunMetadata
from app.agents.schemas import AgentCaseContext, AgentDecision, Diagnosis
from app.agents.tools import ReadOnlyAgentTools
from app.models.enums import CaseType, FailureReason, RecoveryAction, TransactionStatus


class RulesAgentProvider:
    name = "rules"

    def __init__(
        self,
        *,
        configured_provider: str = "rules",
        fallback_reason: str | None = None,
    ) -> None:
        self._configured_provider = configured_provider
        self._fallback_reason = fallback_reason

    def decide(
        self,
        context: AgentCaseContext,
        tools: ReadOnlyAgentTools,
    ) -> AgentProviderResult:
        customer = tools.get_customer()
        transaction = tools.get_transaction()
        history = tools.get_payment_history(limit=10)
        payment_status = tools.check_payment_status()
        tool_calls = (
            "get_customer",
            "get_transaction",
            "get_payment_history",
            "check_payment_status",
        )

        if payment_status.status == TransactionStatus.SUCCESS:
            decision = AgentDecision(
                diagnosis=Diagnosis.UNKNOWN_FAILURE,
                confidence=1.0,
                recommended_action=RecoveryAction.MARK_CASE_RESOLVED,
                reason="The triggering payment is already successful and should be verified before closure.",
                escalation_required=False,
            )
        else:
            previous_failures = sum(
                1
                for item in history
                if item.id != transaction.id
                and not item.is_historical
                and item.status in (TransactionStatus.FAILED, TransactionStatus.ABANDONED)
            )
            decision = self._decision_for(
                context,
                customer_lifetime_value=customer.lifetime_value,
                has_phone=customer.has_phone,
                failure_reason=transaction.failure_reason,
                previous_failures=previous_failures,
            )

        return AgentProviderResult(
            decision=decision,
            metadata=AgentRunMetadata(
                provider=self.name,
                configured_provider=self._configured_provider,
                model="deterministic-rules-v1",
                fallback_reason=self._fallback_reason,
                tool_calls=tool_calls,
            ),
        )

    @staticmethod
    def _decision_for(
        context: AgentCaseContext,
        *,
        customer_lifetime_value: int,
        has_phone: bool,
        failure_reason: FailureReason | None,
        previous_failures: int,
    ) -> AgentDecision:
        limits = context.policy_limits
        requires_human = (
            context.amount_at_risk >= limits["escalation_amount_threshold"]
            or customer_lifetime_value >= limits["high_value_ltv_threshold"]
            or context.retry_count >= limits["max_payment_retries"]
            or context.reminder_count >= limits["max_reminders"]
            or previous_failures >= limits["max_payment_retries"]
        )
        if requires_human:
            return AgentDecision(
                diagnosis=(
                    Diagnosis.MULTIPLE_FAILED_ATTEMPTS
                    if previous_failures >= limits["max_payment_retries"]
                    else _diagnosis(failure_reason)
                ),
                confidence=0.99,
                recommended_action=RecoveryAction.ESCALATE_TO_HUMAN,
                reason="Policy thresholds or repeated failures require careful human review.",
                escalation_required=True,
            )

        if failure_reason in {
            FailureReason.EXPIRED_CARD,
            FailureReason.INVALID_CARD,
            FailureReason.AUTHENTICATION_FAILURE,
            FailureReason.MANDATE_REVOKED,
        }:
            action = RecoveryAction.GENERATE_PAYMENT_LINK
            reason = "The payment method needs customer action, so a secure update link is the safest next step."
        elif failure_reason in {
            FailureReason.TEMPORARY_BANK_FAILURE,
            FailureReason.INSUFFICIENT_FUNDS,
            FailureReason.NETWORK_ERROR,
            FailureReason.CARD_DECLINED,
        }:
            action = RecoveryAction.SCHEDULE_RETRY
            reason = "The failure may be temporary, so a bounded delayed retry is appropriate."
        elif failure_reason == FailureReason.CHECKOUT_ABANDONED:
            action = RecoveryAction.SEND_WHATSAPP if has_phone else RecoveryAction.SEND_EMAIL
            reason = "The checkout was abandoned, so one concise payment reminder is appropriate."
        elif failure_reason == FailureReason.INVOICE_OVERDUE or context.case_type == CaseType.OVERDUE_INVOICE:
            action = RecoveryAction.SEND_EMAIL
            reason = "The overdue invoice requires a documented payment reminder before escalation."
        else:
            action = RecoveryAction.GENERATE_PAYMENT_LINK
            reason = "A secure payment link gives the customer a controlled way to complete payment."

        return AgentDecision(
            diagnosis=_diagnosis(failure_reason),
            confidence=0.96,
            recommended_action=action,
            reason=reason,
            escalation_required=False,
        )


def _diagnosis(reason: FailureReason | None) -> Diagnosis:
    if reason is None:
        return Diagnosis.UNKNOWN_FAILURE
    try:
        return Diagnosis(reason.value)
    except ValueError:
        return Diagnosis.UNKNOWN_FAILURE
