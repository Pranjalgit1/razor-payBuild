"""Database-computed dashboard metrics.

All financial aggregation stays on the backend so paginated UI data can never
produce incomplete or inconsistent headline metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case as sql_case, func
from sqlalchemy.orm import Session, selectinload

from app.models.entities import RecoveryCase
from app.models.enums import CaseStatus

_ACTIVE_STATUSES = (
    CaseStatus.DETECTED.value,
    CaseStatus.DIAGNOSED.value,
    CaseStatus.DECIDED.value,
    CaseStatus.EXECUTING.value,
    CaseStatus.VERIFYING.value,
    CaseStatus.ESCALATED.value,
)


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    revenue_at_risk: int
    revenue_recovered: int
    recovery_rate: float
    active_recovery_cases: int
    total_recovery_cases: int
    recovered_cases: int
    recent_cases: tuple[RecoveryCase, ...]


def get_dashboard(db: Session, *, recent_limit: int = 6) -> DashboardSnapshot:
    """Return one portable aggregate snapshot plus the newest live cases.

    Revenue at risk is the outstanding amount on open or escalated cases.
    Recovery rate is verified recovered money divided by total case value. Both
    values are based on the complete database, never a paginated result set.
    """
    active = RecoveryCase.status.in_(_ACTIVE_STATUSES)
    aggregates = db.query(
        func.coalesce(
            func.sum(
                sql_case(
                    (active, RecoveryCase.amount_at_risk - RecoveryCase.amount_recovered),
                    else_=0,
                )
            ),
            0,
        ).label("revenue_at_risk"),
        func.coalesce(func.sum(RecoveryCase.amount_recovered), 0).label(
            "revenue_recovered"
        ),
        func.coalesce(func.sum(RecoveryCase.amount_at_risk), 0).label(
            "total_case_value"
        ),
        func.count(RecoveryCase.id).label("total_recovery_cases"),
        func.coalesce(func.sum(sql_case((active, 1), else_=0)), 0).label(
            "active_recovery_cases"
        ),
        func.coalesce(
            func.sum(
                sql_case((RecoveryCase.status == CaseStatus.RECOVERED.value, 1), else_=0)
            ),
            0,
        ).label("recovered_cases"),
    ).one()

    total_case_value = int(aggregates.total_case_value)
    revenue_recovered = int(aggregates.revenue_recovered)
    recovery_rate = (
        round(revenue_recovered * 100 / total_case_value, 1)
        if total_case_value
        else 0.0
    )
    recent_cases = tuple(
        db.query(RecoveryCase)
        .options(
            selectinload(RecoveryCase.customer),
            selectinload(RecoveryCase.transaction),
        )
        .order_by(RecoveryCase.created_at.desc())
        .limit(recent_limit)
        .all()
    )

    return DashboardSnapshot(
        revenue_at_risk=int(aggregates.revenue_at_risk),
        revenue_recovered=revenue_recovered,
        recovery_rate=recovery_rate,
        active_recovery_cases=int(aggregates.active_recovery_cases),
        total_recovery_cases=int(aggregates.total_recovery_cases),
        recovered_cases=int(aggregates.recovered_cases),
        recent_cases=recent_cases,
    )
