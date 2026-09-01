"""Application service for structured agent diagnosis and decisions."""

from __future__ import annotations

from dataclasses import dataclass
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

from app.agents import (
    AgentCaseContext,
    AgentConfigurationError,
    AgentDecision,
    AgentInvalidDecision,
    AgentProvider,
    AgentProviderResult,
    AgentRunMetadata,
    build_agent_provider,
)
from app.agents.tools import ReadOnlyAgentTools
from app.config import Settings, settings
from app.models.entities import AgentAction, RecoveryCase
from app.models.enums import ActionStatus, CaseStatus, CaseType, RiskLevel
from app.services.audit import record_action


class AgentWorkflowError(ValueError):
    """The case is not eligible for an agent decision."""


class AgentDecisionRejected(ValueError):
    """The configured provider returned an invalid structured decision."""


@dataclass(slots=True)
class AgentRunResult:
    case: RecoveryCase
    decision: AgentDecision
    metadata: AgentRunMetadata
    audit_actions: tuple[AgentAction, ...]
    idempotent: bool = False


@dataclass(frozen=True, slots=True)
class _CaseVersion:
    status: str
    action_taken: str | None
    retry_count: int
    reminder_count: int
    amount_recovered: int
    scheduled_retry_at: object | None
    transaction_status: str


def run_agent(
    db: Session,
    case: RecoveryCase,
    *,
    provider: AgentProvider | None = None,
    config: Settings = settings,
) -> AgentRunResult:
    """Investigate, validate, persist, and audit one structured decision."""
    existing = _existing_result(case, config)
    if existing is not None:
        return existing
    _assert_agent_eligible(case)
    case_id = case.id
    version = _case_version(case)

    context = _build_context(case, config)
    tools = ReadOnlyAgentTools(db, case)
    try:
        selected_provider = provider or build_agent_provider(config)
        provider_result = selected_provider.decide(context, tools)
        # Providers are required to return this model, but validate a serialized
        # copy again at the trust boundary so custom providers cannot bypass it.
        decision = AgentDecision.model_validate(
            provider_result.decision.model_dump(mode="json")
        )
        decision = decision.model_copy(update={"reason": _public_reason(decision)})
    except (AgentInvalidDecision, AgentConfigurationError) as exc:
        failed = record_action(
            db,
            case_id=case.id,
            action_type="agent_decision_failed",
            reasoning="The agent response failed structured validation and was not applied.",
            status=ActionStatus.FAILED,
            details={"error_category": type(exc).__name__},
        )
        db.flush()
        raise AgentDecisionRejected(str(exc)) from exc

    # Claim the untouched pre-action case with a database compare-and-set. This
    # is effective on SQLite as well as PostgreSQL and prevents a slow provider
    # response from rewinding a workflow that acted while inference was running.
    claimed = _claim_case(db, case_id, version)
    if claimed != 1:
        db.expire_all()
        current = (
            db.query(RecoveryCase)
            .options(selectinload(RecoveryCase.actions))
            .filter(RecoveryCase.id == case_id)
            .one()
        )
        concurrent = _existing_result(current, config)
        if concurrent is not None:
            return concurrent
        raise AgentWorkflowError(
            "The recovery case changed while the agent was running; its stale decision was discarded."
        )

    locked = (
        db.query(RecoveryCase)
        .options(
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.transaction),
            selectinload(RecoveryCase.actions),
        )
        .filter(RecoveryCase.id == case_id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if locked.transaction.status != version.transaction_status:
        raise AgentWorkflowError(
            "The payment changed while the agent was running; its stale decision was discarded."
        )

    locked.diagnosis = decision.diagnosis.value
    locked.confidence = decision.confidence
    locked.status = CaseStatus.DIAGNOSED
    metadata_details = _metadata_dict(provider_result)
    diagnosis_audit = record_action(
        db,
        case_id=locked.id,
        action_type="agent_diagnosis_completed",
        reasoning=f"Diagnosed {decision.diagnosis.value.replace('_', ' ')} with {decision.confidence:.0%} confidence.",
        details={
            **metadata_details,
            "diagnosis": decision.diagnosis.value,
            "confidence": decision.confidence,
        },
    )

    locked.recommended_action = decision.recommended_action.value
    locked.decision_reason = decision.reason
    locked.escalation_required = decision.escalation_required
    locked.status = CaseStatus.DECIDED
    decision_audit = record_action(
        db,
        case_id=locked.id,
        action_type="agent_decision_recorded",
        reasoning=(
            f"Recommended {decision.recommended_action.value.replace('_', ' ')} "
            f"after a validated {decision.diagnosis.value.replace('_', ' ')} diagnosis."
        ),
        details={
            **metadata_details,
            "recommended_action": decision.recommended_action.value,
            "escalation_required": decision.escalation_required,
        },
    )
    db.flush()
    return AgentRunResult(
        case=locked,
        decision=decision,
        metadata=provider_result.metadata,
        audit_actions=(diagnosis_audit, decision_audit),
    )


def _claim_case(db: Session, case_id: int, version: _CaseVersion) -> int:
    """Claim one untouched case, retrying transient SQLite writer contention."""
    for attempt in range(6):
        try:
            return (
                db.query(RecoveryCase)
                .filter(
                    RecoveryCase.id == case_id,
                    RecoveryCase.status == version.status,
                    RecoveryCase.diagnosis.is_(None),
                    RecoveryCase.recommended_action.is_(None),
                    RecoveryCase.action_taken.is_(None),
                    RecoveryCase.retry_count == version.retry_count,
                    RecoveryCase.reminder_count == version.reminder_count,
                    RecoveryCase.amount_recovered == version.amount_recovered,
                    RecoveryCase.scheduled_retry_at.is_(None),
                )
                .update(
                    {RecoveryCase.status: CaseStatus.DIAGNOSED},
                    synchronize_session=False,
                )
            )
        except OperationalError as exc:
            is_sqlite_lock = (
                db.bind is not None
                and db.bind.dialect.name == "sqlite"
                and "locked" in str(exc).casefold()
            )
            if not is_sqlite_lock:
                raise
            db.rollback()
            time.sleep(0.05 * (attempt + 1))
    return 0


def _assert_agent_eligible(case: RecoveryCase) -> None:
    if case.is_terminal:
        raise AgentWorkflowError("A terminal recovery case cannot run the agent.")
    if case.status == CaseStatus.ESCALATED:
        raise AgentWorkflowError("An escalated case is already assigned to a human.")
    if case.status != CaseStatus.DETECTED or case.action_taken is not None:
        raise AgentWorkflowError("Only an untouched detected case can run the agent.")
    if case.risk_score is None or case.risk_level is None:
        raise AgentWorkflowError("Calculate deterministic risk before running the agent.")


def _case_version(case: RecoveryCase) -> _CaseVersion:
    return _CaseVersion(
        status=case.status,
        action_taken=case.action_taken,
        retry_count=case.retry_count,
        reminder_count=case.reminder_count,
        amount_recovered=case.amount_recovered,
        scheduled_retry_at=case.scheduled_retry_at,
        transaction_status=case.transaction.status,
    )


def _public_reason(decision: AgentDecision) -> str:
    """Return backend-owned public prose; provider free text is never persisted."""
    action_text = decision.recommended_action.value.replace("_", " ")
    diagnosis_text = decision.diagnosis.value.replace("_", " ")
    if decision.recommended_action.value == "escalate_to_human":
        return f"The {diagnosis_text} case needs human review before another recovery step."
    if decision.recommended_action.value == "schedule_retry":
        return f"The {diagnosis_text} may be temporary, so a bounded retry should be scheduled."
    if decision.recommended_action.value == "generate_payment_link":
        return f"The {diagnosis_text} requires a secure customer payment or method-update link."
    if decision.recommended_action.value in {"send_email", "send_whatsapp"}:
        return f"The {diagnosis_text} requires one policy-limited customer reminder."
    if decision.recommended_action.value == "retry_payment":
        return f"The {diagnosis_text} is retryable within the backend payment-attempt limit."
    return f"The validated {diagnosis_text} supports the controlled action: {action_text}."


def _build_context(case: RecoveryCase, config: Settings) -> AgentCaseContext:
    return AgentCaseContext(
        case_id=case.id,
        customer_id=case.customer_id,
        transaction_id=case.transaction_id,
        case_type=CaseType(case.case_type),
        status=CaseStatus(case.status),
        amount_at_risk=case.amount_at_risk,
        risk_score=case.risk_score,
        risk_level=RiskLevel(case.risk_level),
        risk_factors=case.risk_factors or [],
        retry_count=case.retry_count,
        reminder_count=case.reminder_count,
        has_scheduled_retry=case.scheduled_retry_at is not None,
        policy_limits={
            "max_payment_retries": config.max_payment_retries,
            "max_reminders": config.max_reminders,
            "contact_cooldown_hours": config.contact_cooldown_hours,
            "escalation_amount_threshold": config.escalation_amount_threshold,
            "high_value_ltv_threshold": config.high_value_ltv_threshold,
        },
    )


def _existing_result(
    case: RecoveryCase,
    config: Settings,
) -> AgentRunResult | None:
    if not all(
        (
            case.diagnosis,
            case.confidence is not None,
            case.recommended_action,
            case.decision_reason,
        )
    ):
        return None
    decision = AgentDecision.model_validate(
        {
            "diagnosis": case.diagnosis,
            "confidence": case.confidence,
            "recommended_action": case.recommended_action,
            "reason": case.decision_reason,
            "escalation_required": case.escalation_required,
        }
    )
    audits = tuple(
        action
        for action in case.actions
        if action.action_type in {"agent_diagnosis_completed", "agent_decision_recorded"}
    )
    decision_audit = next(
        (action for action in reversed(audits) if action.action_type == "agent_decision_recorded"),
        None,
    )
    details = decision_audit.details if decision_audit and decision_audit.details else {}
    metadata = AgentRunMetadata(
        provider=str(details.get("provider", "persisted")),
        configured_provider=str(details.get("configured_provider", config.ai_provider)),
        model=details.get("model"),
        request_id=details.get("request_id"),
        fallback_reason=details.get("fallback_reason"),
        tool_calls=tuple(details.get("tool_calls", [])),
    )
    return AgentRunResult(case, decision, metadata, audits, idempotent=True)


def _metadata_dict(result: AgentProviderResult) -> dict:
    metadata = result.metadata
    return {
        "provider": metadata.provider,
        "configured_provider": metadata.configured_provider,
        "model": metadata.model,
        "request_id": metadata.request_id,
        "fallback_reason": metadata.fallback_reason,
        "tool_calls": list(metadata.tool_calls),
    }
