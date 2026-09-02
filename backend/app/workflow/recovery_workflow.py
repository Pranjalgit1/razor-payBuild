"""Recovery state machine and policy-enforced orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.database.base import utcnow
from app.models.entities import AgentAction, RecoveryCase, Transaction
from app.models.enums import (
    ActionStatus,
    CaseStatus,
    FailureReason,
    RecoveryAction,
    TransactionStatus,
)
from app.services import payment_service
from app.services.audit import record_action
from app.services.recovery_action_service import ActionExecution, execute_action
from app.workflow.policy_guard import PolicyDecision, validate_action


class RecoveryWorkflowError(ValueError):
    """The requested operation is invalid for the case's current state."""


@dataclass(slots=True)
class RecoveryWorkflowResult:
    case: RecoveryCase
    decision: PolicyDecision
    audit_action: AgentAction
    execution: ActionExecution | None = None

    @property
    def executed(self) -> bool:
        return self.execution is not None and self.audit_action.status == ActionStatus.SUCCESS


def run_action(
    db: Session,
    case: RecoveryCase,
    action: RecoveryAction,
    *,
    policy: Settings = settings,
    action_source: str = "manual_operator",
) -> RecoveryWorkflowResult:
    """Validate, audit, and execute one controlled recovery action atomically."""
    decision = validate_action(case, action, policy=policy)
    policy_details = {
        "action": action.value,
        "action_source": action_source,
        "agent_recommended_action": case.recommended_action,
        "policy_code": decision.code,
        "escalation_required": decision.escalation_required,
        "limits": {
            "max_payment_retries": policy.max_payment_retries,
            "max_reminders": policy.max_reminders,
            "contact_cooldown_hours": policy.contact_cooldown_hours,
            "escalation_amount_threshold": policy.escalation_amount_threshold,
            "high_value_ltv_threshold": policy.high_value_ltv_threshold,
        },
        "current": {
            "retry_count": case.retry_count,
            "reminder_count": case.reminder_count,
            "amount_at_risk": case.amount_at_risk,
            "customer_lifetime_value": case.customer.lifetime_value,
        },
    }

    if not decision.allowed:
        blocked = record_action(
            db,
            case_id=case.id,
            action_type="recovery_action_blocked",
            reasoning=decision.reason,
            status=ActionStatus.BLOCKED,
            details=policy_details,
        )
        if decision.escalation_required:
            case.status = CaseStatus.ESCALATED
            case.escalation_required = True
            case.action_taken = RecoveryAction.ESCALATE_TO_HUMAN.value
            record_action(
                db,
                case_id=case.id,
                action_type="recovery_escalated",
                reasoning="Policy limits require a human recovery specialist.",
                details={
                    "trigger": decision.code,
                    "blocked_action": action.value,
                    "queue": "human_recovery_review",
                },
            )
        db.flush()
        return RecoveryWorkflowResult(case, decision, blocked)

    record_action(
        db,
        case_id=case.id,
        action_type="recovery_action_approved",
        reasoning=decision.reason,
        details=policy_details,
    )
    try:
        # A savepoint prevents a partially applied side effect from leaking into
        # the case while still allowing the failure itself to be audited.
        with db.begin_nested():
            execution = execute_action(
                db,
                case,
                action,
                schedule_delay_hours=policy.contact_cooldown_hours,
            )
    except Exception as exc:
        db.refresh(case)
        failed = record_action(
            db,
            case_id=case.id,
            action_type="recovery_action_failed",
            reasoning=f"The approved {action.value.replace('_', ' ')} action failed.",
            status=ActionStatus.FAILED,
            details={"action": action.value, "error": type(exc).__name__},
        )
        db.flush()
        return RecoveryWorkflowResult(case, decision, failed)

    completed = record_action(
        db,
        case_id=case.id,
        action_type="recovery_action_executed",
        reasoning=f"Executed {action.value.replace('_', ' ')} after policy approval.",
        details=execution.details,
    )
    db.flush()
    return RecoveryWorkflowResult(case, decision, completed, execution)


def record_customer_payment(
    db: Session,
    case: RecoveryCase,
    *,
    amount: int | None,
    succeed: bool,
    failure_reason: FailureReason | None,
) -> Transaction:
    """Verify a customer payment and update recovery money/state atomically."""
    if case.is_terminal or case.status == CaseStatus.ESCALATED:
        raise RecoveryWorkflowError("This case is not accepting automated payments.")
    if case.action_taken is None:
        raise RecoveryWorkflowError("Execute a recovery action before verifying payment.")
    payment_actions = {
        RecoveryAction.RETRY_PAYMENT,
        RecoveryAction.GENERATE_PAYMENT_LINK,
        RecoveryAction.SEND_EMAIL,
        RecoveryAction.SEND_WHATSAPP,
    }
    if case.action_taken not in payment_actions:
        raise RecoveryWorkflowError(
            "The executed action does not produce a customer payment to verify."
        )

    remaining = case.amount_at_risk - case.amount_recovered
    payment_amount = remaining if amount is None else amount
    if payment_amount <= 0 or payment_amount > remaining:
        raise RecoveryWorkflowError(
            f"Payment amount must be between 1 and the remaining {remaining} paise."
        )

    if case.action_taken == RecoveryAction.RETRY_PAYMENT:
        transaction = (
            db.query(Transaction)
            .filter(
                Transaction.parent_transaction_id == case.transaction_id,
                Transaction.status == TransactionStatus.PENDING,
            )
            .order_by(Transaction.id.desc())
            .with_for_update()
            .first()
        )
        if transaction is None:
            raise RecoveryWorkflowError("The approved retry attempt is missing.")
        if payment_amount != transaction.amount:
            raise RecoveryWorkflowError(
                f"The approved retry amount is {transaction.amount} paise."
            )
        transaction = payment_service.complete_pending_payment(
            db,
            transaction,
            succeed=succeed,
            failure_reason=failure_reason,
        )
    else:
        transaction = payment_service.create_payment(
            db,
            customer=case.customer,
            amount=payment_amount,
            succeed=succeed,
            failure_reason=failure_reason,
            attempt_number=case.transaction.attempt_number + case.retry_count + 1,
            parent_transaction_id=case.transaction_id,
            currency=case.transaction.currency,
        )

    if succeed:
        case.amount_recovered += payment_amount
        if case.amount_recovered == case.amount_at_risk:
            case.status = CaseStatus.RECOVERED
            case.resolved_at = utcnow()
        else:
            case.status = CaseStatus.VERIFYING
        record_action(
            db,
            case_id=case.id,
            action_type="recovery_payment_verified",
            reasoning=(
                f"Verified {payment_amount / 100:,.2f} INR received from the customer."
            ),
            details={
                "transaction_id": transaction.id,
                "amount_recovered": payment_amount,
                "total_recovered": case.amount_recovered,
                "case_status": case.status,
                "source_action": case.action_taken,
            },
        )
    else:
        case.status = CaseStatus.VERIFYING
        record_action(
            db,
            case_id=case.id,
            action_type="recovery_payment_failed",
            reasoning="The customer payment attempt failed; no revenue was recovered.",
            status=ActionStatus.FAILED,
            details={
                "transaction_id": transaction.id,
                "failure_reason": transaction.failure_reason,
                "source_action": case.action_taken,
            },
        )
    db.flush()
    return transaction
