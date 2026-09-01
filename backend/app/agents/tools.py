"""Case-scoped, read-only investigation tools exposed to agent providers."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.base import AgentInvalidDecision
from app.agents.schemas import (
    CustomerToolResult,
    PaymentHistoryItem,
    PaymentHistoryToolInput,
    PaymentStatusToolResult,
    TransactionToolResult,
)
from app.models.entities import Customer, RecoveryCase, Transaction
from app.services.payment_service import get_payment_history


class ReadOnlyAgentTools:
    """A narrow gateway that cannot mutate data or inspect another case."""

    ALLOWED_NAMES = frozenset(
        {
            "get_customer",
            "get_transaction",
            "get_payment_history",
            "check_payment_status",
        }
    )

    def __init__(self, db: Session, case: RecoveryCase) -> None:
        self._db = db
        self._case_id = case.id
        self._customer_id = case.customer_id
        self._transaction_id = case.transaction_id

    def get_customer(self) -> CustomerToolResult:
        customer = self._db.get(Customer, self._customer_id)
        if customer is None:
            raise AgentInvalidDecision("The case customer no longer exists.")
        return CustomerToolResult(
            id=customer.id,
            lifetime_value=customer.lifetime_value,
            subscription_status=customer.subscription_status,
            days_until_cancellation=customer.days_until_cancellation,
            is_business=customer.is_business,
            has_email=bool(customer.email),
            has_phone=bool(customer.phone),
        )

    def get_transaction(self) -> TransactionToolResult:
        transaction = self._scoped_transaction()
        return TransactionToolResult.model_validate(
            {
                "id": transaction.id,
                "customer_id": transaction.customer_id,
                "amount": transaction.amount,
                "currency": transaction.currency,
                "status": transaction.status,
                "failure_reason": transaction.failure_reason,
                "attempt_number": transaction.attempt_number,
                "parent_transaction_id": transaction.parent_transaction_id,
                "is_historical": transaction.is_historical,
            }
        )

    def get_payment_history(self, *, limit: int = 10) -> list[PaymentHistoryItem]:
        if not 1 <= limit <= 20:
            raise AgentInvalidDecision("Payment history limit must be between 1 and 20.")
        return [
            PaymentHistoryItem.model_validate(
                {
                    "id": row.id,
                    "customer_id": row.customer_id,
                    "amount": row.amount,
                    "currency": row.currency,
                    "status": row.status,
                    "failure_reason": row.failure_reason,
                    "attempt_number": row.attempt_number,
                    "parent_transaction_id": row.parent_transaction_id,
                    "is_historical": row.is_historical,
                }
            )
            for row in get_payment_history(self._db, self._customer_id, limit=limit)
        ]

    def check_payment_status(self) -> PaymentStatusToolResult:
        transaction = self._scoped_transaction()
        return PaymentStatusToolResult(
            transaction_id=transaction.id,
            status=transaction.status,
            failure_reason=transaction.failure_reason,
        )

    def invoke(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Dispatch a provider tool call after strict name/input validation."""
        arguments = arguments or {}
        if name not in self.ALLOWED_NAMES:
            raise AgentInvalidDecision(f"Agent attempted forbidden tool: {name}.")
        if name == "get_payment_history":
            unknown = set(arguments) - {"limit"}
            if unknown:
                raise AgentInvalidDecision("get_payment_history received unknown inputs.")
            try:
                parsed = PaymentHistoryToolInput.model_validate(arguments)
            except ValidationError as exc:
                raise AgentInvalidDecision(
                    "get_payment_history received invalid inputs."
                ) from exc
            return [
                item.model_dump(mode="json")
                for item in self.get_payment_history(limit=parsed.limit)
            ]
        if arguments:
            raise AgentInvalidDecision(f"{name} does not accept inputs.")
        result = getattr(self, name)()
        return result.model_dump(mode="json")

    def _scoped_transaction(self) -> Transaction:
        transaction = self._db.get(Transaction, self._transaction_id)
        if transaction is None or transaction.customer_id != self._customer_id:
            raise AgentInvalidDecision("The case transaction no longer exists.")
        return transaction
