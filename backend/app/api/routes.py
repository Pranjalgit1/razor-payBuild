"""REST API routers.

Routers stay thin: they validate input, call a service, and shape the response.
All business logic lives in ``app.services`` (PRD rule: keep business logic on
the backend, and keep it out of the transport layer).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.database.session import get_db
from app.models.entities import AgentAction, Customer, RecoveryCase, Transaction
from app.models.enums import (
    CaseStatus,
    CaseType,
    RecoveryAction,
    RiskLevel,
    TransactionStatus,
)
from app.schemas.schemas import (
    AgentActionRead,
    CustomerCreate,
    CustomerRead,
    OperationResult,
    Page,
    PaymentSimulationRequest,
    PaymentSimulationResponse,
    RecoveryActionRequest,
    RecoveryActionResponse,
    RecoveryCaseDetail,
    RecoveryCaseListItem,
    RecoveryCaseRead,
    RecoveryPaymentRequest,
    RecoveryPaymentResponse,
    RunAgentResponse,
    TransactionRead,
)
from app.services import agent_service, case_service, payment_service, risk_service
from app.simulations.seed import reset_demo_data, seed_demo_data
from app.workflow import RecoveryWorkflowError, record_customer_payment, run_action

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

customers_router = APIRouter(prefix="/customers", tags=["customers"])


@customers_router.get("", response_model=Page[CustomerRead])
def list_customers(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, description="Match on name or email"),
) -> Page[CustomerRead]:
    query = db.query(Customer)
    if search:
        pattern = f"%{search.lower()}%"
        query = query.filter(
            func.lower(Customer.name).like(pattern)
            | func.lower(Customer.email).like(pattern)
        )

    total = query.count()
    rows = query.order_by(Customer.lifetime_value.desc()).offset(offset).limit(limit).all()
    return Page(
        items=[CustomerRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@customers_router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(customer_id: int, db: Session = Depends(get_db)) -> CustomerRead:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return CustomerRead.model_validate(customer)


@customers_router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)) -> CustomerRead:
    existing = db.query(Customer).filter(Customer.email == payload.email).one_or_none()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A customer with email {payload.email} already exists"
        )
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    return CustomerRead.model_validate(customer)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

transactions_router = APIRouter(prefix="/transactions", tags=["transactions"])


@transactions_router.get("", response_model=Page[TransactionRead])
def list_transactions(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    customer_id: int | None = None,
    transaction_status: TransactionStatus | None = Query(None, alias="status"),
    include_historical: bool = True,
) -> Page[TransactionRead]:
    query = db.query(Transaction)
    if customer_id is not None:
        query = query.filter(Transaction.customer_id == customer_id)
    if transaction_status is not None:
        query = query.filter(Transaction.status == transaction_status.value)
    if not include_historical:
        query = query.filter(Transaction.is_historical.is_(False))

    total = query.count()
    rows = query.order_by(Transaction.created_at.desc()).offset(offset).limit(limit).all()
    return Page(
        items=[TransactionRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@transactions_router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)) -> TransactionRead:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return TransactionRead.model_validate(transaction)


# ---------------------------------------------------------------------------
# Payments / simulation
# ---------------------------------------------------------------------------

payments_router = APIRouter(prefix="/payments", tags=["payments"])


@payments_router.post(
    "/simulate",
    response_model=PaymentSimulationResponse,
    status_code=status.HTTP_201_CREATED,
)
def simulate_payment(
    payload: PaymentSimulationRequest, db: Session = Depends(get_db)
) -> PaymentSimulationResponse:
    """Create a simulated payment event.

    A failed payment automatically opens a recovery case — this is the DETECT
    stage firing, not a separate manual step.
    """
    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    try:
        transaction = payment_service.create_payment(
            db,
            customer=customer,
            amount=payload.amount,
            succeed=payload.succeed,
            failure_reason=payload.resolved_failure_reason(),
        )
    except payment_service.PaymentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    case = case_service.detect_revenue_at_risk(db, transaction)
    if case is not None:
        risk_service.score_case(db, case)
    db.commit()

    if case is None:
        message = "Payment succeeded. No revenue at risk, so no recovery case was opened."
    else:
        message = (
            f"Payment failed. Recovery case #{case.id} opened for "
            f"{transaction.amount / 100:,.2f} INR at risk."
        )

    return PaymentSimulationResponse(
        transaction=TransactionRead.model_validate(transaction),
        recovery_case=RecoveryCaseRead.model_validate(case) if case else None,
        message=message,
    )


# ---------------------------------------------------------------------------
# Recovery cases
# ---------------------------------------------------------------------------

cases_router = APIRouter(prefix="/recovery-cases", tags=["recovery-cases"])


def _get_case_for_workflow(db: Session, case_id: int) -> RecoveryCase:
    """Load one case and lock it where the database supports row locks."""
    case = (
        db.query(RecoveryCase)
        .options(
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.transaction),
            selectinload(RecoveryCase.actions),
        )
        .filter(RecoveryCase.id == case_id)
        .with_for_update()
        .one_or_none()
    )
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recovery case not found")
    return case


@cases_router.post("/{case_id}/run-agent", response_model=RunAgentResponse)
def run_recovery_agent(
    case_id: int,
    db: Session = Depends(get_db),
) -> RunAgentResponse:
    """Run the structured decision layer without executing its proposal."""
    case = (
        db.query(RecoveryCase)
        .options(
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.transaction),
            selectinload(RecoveryCase.actions),
        )
        .filter(RecoveryCase.id == case_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recovery case not found")
    try:
        result = agent_service.run_agent(db, case)
    except agent_service.AgentWorkflowError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except agent_service.AgentDecisionRejected as exc:
        # The rejection audit is safe to commit; no decision fields were applied.
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Agent decision failed structured validation.",
        ) from exc
    db.commit()

    return RunAgentResponse(
        case=RecoveryCaseRead.model_validate(result.case),
        decision=result.decision,
        metadata={
            "provider": result.metadata.provider,
            "configured_provider": result.metadata.configured_provider,
            "model": result.metadata.model,
            "request_id": result.metadata.request_id,
            "fallback_reason": result.metadata.fallback_reason,
            "tool_calls": list(result.metadata.tool_calls),
        },
        audit_actions=[AgentActionRead.model_validate(a) for a in result.audit_actions],
        idempotent=result.idempotent,
        message=(
            "Existing validated agent decision returned."
            if result.idempotent
            else "Agent diagnosis and controlled action proposal recorded."
        ),
    )


@cases_router.post("/{case_id}/execute", response_model=RecoveryActionResponse)
def execute_recovery_action(
    case_id: int,
    payload: RecoveryActionRequest,
    db: Session = Depends(get_db),
) -> RecoveryActionResponse:
    """Execute an agent recommendation or an explicit operator action."""
    case = _get_case_for_workflow(db, case_id)
    recommended = (
        RecoveryAction(case.recommended_action)
        if case.recommended_action is not None
        else None
    )
    scheduled_transition = (
        recommended == RecoveryAction.SCHEDULE_RETRY
        and case.action_taken == RecoveryAction.SCHEDULE_RETRY
        and case.scheduled_retry_at is not None
    )
    if payload.action is None:
        if recommended is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Run the recovery agent or provide an explicit operator action.",
            )
        if scheduled_transition:
            selected_action = RecoveryAction.RETRY_PAYMENT
            action_source = "scheduled_agent_transition"
        else:
            selected_action = recommended
            action_source = "agent_recommendation"
    else:
        selected_action = payload.action
        is_due_retry_transition = (
            scheduled_transition and selected_action == RecoveryAction.RETRY_PAYMENT
        )
        if (
            recommended is not None
            and selected_action != recommended
            and selected_action != RecoveryAction.ESCALATE_TO_HUMAN
            and not is_due_retry_transition
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The requested action does not match the validated agent recommendation.",
            )
        action_source = (
            "scheduled_agent_transition"
            if is_due_retry_transition
            else "agent_recommendation"
            if selected_action == recommended
            else "manual_operator"
        )

    pending_retry = (
        db.query(Transaction.id)
        .filter(
            Transaction.parent_transaction_id == case.transaction_id,
            Transaction.status == TransactionStatus.PENDING,
        )
        .first()
    )
    if pending_retry is not None and selected_action != RecoveryAction.ESCALATE_TO_HUMAN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A payment retry is already pending verification for this case.",
        )

    result = run_action(
        db,
        case,
        selected_action,
        action_source=action_source,
    )
    db.commit()

    details = result.execution.details if result.execution is not None else {}
    if result.executed:
        message = f"Recovery action {selected_action.value} executed."
    elif result.decision.allowed:
        message = f"Recovery action {selected_action.value} failed during execution."
    elif result.decision.escalation_required:
        message = "Action blocked by policy; case escalated for human review."
    else:
        message = "Action blocked by backend recovery policy."

    return RecoveryActionResponse(
        case=RecoveryCaseRead.model_validate(case),
        policy={
            "allowed": result.decision.allowed,
            "code": result.decision.code,
            "reason": result.decision.reason,
            "escalation_required": result.decision.escalation_required,
        },
        executed=result.executed,
        audit_action=AgentActionRead.model_validate(result.audit_action),
        details=details,
        message=message,
    )


@cases_router.post(
    "/{case_id}/simulate-payment",
    response_model=RecoveryPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def simulate_recovery_payment(
    case_id: int,
    payload: RecoveryPaymentRequest,
    db: Session = Depends(get_db),
) -> RecoveryPaymentResponse:
    """Simulate and verify the customer's payment after an approved action."""
    case = _get_case_for_workflow(db, case_id)
    try:
        transaction = record_customer_payment(
            db,
            case,
            amount=payload.amount,
            succeed=payload.succeed,
            failure_reason=payload.resolved_failure_reason(),
        )
    except RecoveryWorkflowError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()

    message = (
        "Customer payment verified; the case is recovered."
        if case.status == CaseStatus.RECOVERED
        else "Customer payment recorded; recovery remains in progress."
    )
    return RecoveryPaymentResponse(
        case=RecoveryCaseRead.model_validate(case),
        transaction=TransactionRead.model_validate(transaction),
        message=message,
    )


@cases_router.get("", response_model=Page[RecoveryCaseListItem])
def list_recovery_cases(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    case_status: CaseStatus | None = Query(None, alias="status"),
    risk_level: RiskLevel | None = None,
    case_type: CaseType | None = None,
    customer_id: int | None = None,
    min_amount: int | None = Query(None, ge=0, description="Paise"),
    max_amount: int | None = Query(None, ge=0, description="Paise"),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> Page[RecoveryCaseListItem]:
    query = db.query(RecoveryCase).options(selectinload(RecoveryCase.customer))

    if case_status is not None:
        query = query.filter(RecoveryCase.status == case_status.value)
    if risk_level is not None:
        query = query.filter(RecoveryCase.risk_level == risk_level.value)
    if case_type is not None:
        query = query.filter(RecoveryCase.case_type == case_type.value)
    if customer_id is not None:
        query = query.filter(RecoveryCase.customer_id == customer_id)
    if min_amount is not None:
        query = query.filter(RecoveryCase.amount_at_risk >= min_amount)
    if max_amount is not None:
        query = query.filter(RecoveryCase.amount_at_risk <= max_amount)
    if created_after is not None:
        query = query.filter(RecoveryCase.created_at >= created_after)
    if created_before is not None:
        query = query.filter(RecoveryCase.created_at <= created_before)

    total = query.count()
    rows = query.order_by(RecoveryCase.created_at.desc()).offset(offset).limit(limit).all()
    return Page(
        items=[RecoveryCaseListItem.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@cases_router.get("/{case_id}", response_model=RecoveryCaseDetail)
def get_recovery_case(case_id: int, db: Session = Depends(get_db)) -> RecoveryCaseDetail:
    case = (
        db.query(RecoveryCase)
        .options(
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.transaction),
            selectinload(RecoveryCase.actions),
            selectinload(RecoveryCase.messages),
        )
        .filter(RecoveryCase.id == case_id)
        .one_or_none()
    )
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recovery case not found")
    return RecoveryCaseDetail.model_validate(case)


# ---------------------------------------------------------------------------
# Agent activity
# ---------------------------------------------------------------------------

agent_router = APIRouter(prefix="/agent", tags=["agent"])


@agent_router.get("/actions", response_model=Page[AgentActionRead])
def list_agent_actions(
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    case_id: int | None = None,
) -> Page[AgentActionRead]:
    query = db.query(AgentAction)
    if case_id is not None:
        query = query.filter(AgentAction.recovery_case_id == case_id)

    total = query.count()
    rows = query.order_by(AgentAction.timestamp.desc()).offset(offset).limit(limit).all()
    return Page(
        items=[AgentActionRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Demo controls
# ---------------------------------------------------------------------------

demo_router = APIRouter(prefix="/demo", tags=["demo"])


@demo_router.post("/seed", response_model=OperationResult)
def seed_demo(db: Session = Depends(get_db), reset: bool = True) -> OperationResult:
    counts = seed_demo_data(db, reset=reset)
    return OperationResult(
        message=(
            f"Seeded {counts['customers']} customers and "
            f"{counts['transactions']} transactions."
        ),
        detail=counts,
    )


@demo_router.post("/reset", response_model=OperationResult)
def reset_demo(db: Session = Depends(get_db)) -> OperationResult:
    """Clear all data and reseed, returning the demo to a known state."""
    counts = seed_demo_data(db, reset=True)
    return OperationResult(message="Demo data reset.", detail=counts)


@demo_router.delete("/data", response_model=OperationResult)
def clear_demo(db: Session = Depends(get_db)) -> OperationResult:
    reset_demo_data(db)
    return OperationResult(message="All data cleared.")


for sub in (
    customers_router,
    transactions_router,
    payments_router,
    cases_router,
    agent_router,
    demo_router,
):
    router.include_router(sub)
