"""Contracts for deterministic revenue-risk scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.enums import FailureReason, RiskLevel, SubscriptionStatus


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Validated inputs used by a risk engine.

    Keeping this independent from SQLAlchemy makes the scoring rules pure,
    deterministic, and straightforward to replace with another implementation.
    """

    transaction_amount: int
    customer_lifetime_value: int
    subscription_status: SubscriptionStatus
    previous_failures: int
    days_until_cancellation: int | None
    failure_reason: FailureReason | None
    historical_transactions: int
    historical_failures: int


@dataclass(frozen=True, slots=True)
class RiskFactor:
    label: str
    detail: str
    points: int

    def as_dict(self) -> dict[str, str | int]:
        return {"label": self.label, "detail": self.detail, "points": self.points}


@dataclass(frozen=True, slots=True)
class RiskResult:
    score: int
    level: RiskLevel
    factors: tuple[RiskFactor, ...]


class RiskEngine(Protocol):
    """Interface implemented by every deterministic or ML risk engine."""

    def score(self, context: RiskContext) -> RiskResult: ...
