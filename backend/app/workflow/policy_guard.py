"""Authoritative backend policy for controlled recovery actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.config import Settings, settings
from app.database.base import utcnow
from app.models.entities import RecoveryCase
from app.models.enums import (
    ActionStatus,
    CaseStatus,
    FailureReason,
    RecoveryAction,
    RETRYABLE_FAILURE_REASONS,
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    reason: str
    escalation_required: bool = False


def validate_action(
    case: RecoveryCase,
    action: RecoveryAction,
    *,
    policy: Settings = settings,
) -> PolicyDecision:
    """Allow or refuse an action without performing any side effect."""
    if case.is_terminal:
        return _blocked("terminal_case", "Recovery is already finished for this case.")

    if case.status == CaseStatus.ESCALATED:
        return _blocked("already_escalated", "This case is already assigned to a human.")

    # Human escalation is the one safe action that must remain available even
    # when every automated path is prohibited.
    if action == RecoveryAction.ESCALATE_TO_HUMAN:
        return _allowed("Human escalation is always permitted.")

    if case.risk_score is None:
        return _blocked(
            "risk_not_scored",
            "A deterministic risk score is required before automated recovery.",
        )

    if case.amount_at_risk >= policy.escalation_amount_threshold:
        return _blocked(
            "amount_requires_escalation",
            "The amount at risk meets the mandatory human-escalation threshold.",
            escalation_required=True,
        )

    if case.customer.lifetime_value >= policy.high_value_ltv_threshold:
        return _blocked(
            "high_value_customer",
            "This high-value customer requires human review before recovery.",
            escalation_required=True,
        )

    if _same_action_failed(case, action):
        return _blocked(
            "repeated_failed_action",
            "The same recovery action already failed and cannot be repeated.",
            escalation_required=True,
        )

    if action in (RecoveryAction.RETRY_PAYMENT, RecoveryAction.SCHEDULE_RETRY):
        if case.retry_count >= policy.max_payment_retries:
            return _blocked(
                "retry_limit_reached",
                f"The maximum of {policy.max_payment_retries} payment retries is reached.",
                escalation_required=True,
            )
        try:
            reason = FailureReason(case.transaction.failure_reason)
        except (TypeError, ValueError):
            reason = None
        if reason not in RETRYABLE_FAILURE_REASONS:
            return _blocked(
                "failure_not_retryable",
                "The original failure is not safe to retry on the same payment instrument.",
            )

        now = utcnow()
        if (
            action == RecoveryAction.SCHEDULE_RETRY
            and case.scheduled_retry_at is not None
            and case.scheduled_retry_at > now
        ):
            return _blocked(
                "retry_already_scheduled",
                "A future payment retry is already scheduled for this case.",
            )
        if (
            action == RecoveryAction.RETRY_PAYMENT
            and case.scheduled_retry_at is not None
            and case.scheduled_retry_at > now
        ):
            return _blocked(
                "retry_not_due",
                "The scheduled retry time has not been reached yet.",
            )

    if action in (RecoveryAction.SEND_EMAIL, RecoveryAction.SEND_WHATSAPP):
        if case.reminder_count >= policy.max_reminders:
            return _blocked(
                "reminder_limit_reached",
                f"The maximum of {policy.max_reminders} reminders is reached.",
                escalation_required=True,
            )
        if action == RecoveryAction.SEND_WHATSAPP and not case.customer.phone:
            return _blocked("missing_phone", "The customer has no WhatsApp phone number.")
        if case.last_contact_at is not None:
            next_contact = case.last_contact_at + timedelta(
                hours=policy.contact_cooldown_hours
            )
            if utcnow() < next_contact:
                return _blocked(
                    "contact_cooldown",
                    f"Customer contact is limited to once every {policy.contact_cooldown_hours} hours.",
                )

    if action == RecoveryAction.MARK_CASE_RESOLVED:
        return _blocked(
            "verification_required",
            "Cases can only be resolved after a successful payment is verified.",
        )

    return _allowed("The proposed action satisfies all backend policy limits.")


def _same_action_failed(case: RecoveryCase, action: RecoveryAction) -> bool:
    for audit in reversed(case.actions):
        if audit.status != ActionStatus.FAILED:
            continue
        details = audit.details or {}
        attempted = details.get("action") or details.get("source_action")
        if attempted == action.value:
            return True
    return False


def _allowed(reason: str) -> PolicyDecision:
    return PolicyDecision(True, "allowed", reason)


def _blocked(
    code: str,
    reason: str,
    *,
    escalation_required: bool = False,
) -> PolicyDecision:
    return PolicyDecision(False, code, reason, escalation_required)
