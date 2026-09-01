"""Demo seed data.

Gives the demo a realistic starting state: a spread of customers across value
tiers and subscription states, plus enough transaction history that the risk
engine and the dashboard have something meaningful to work with on first load.

Amounts are in paise.
"""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models.entities import AgentAction, Customer, Message, RecoveryCase, Transaction
from app.models.enums import (
    FailureReason,
    SubscriptionStatus,
    TransactionStatus,
)

#: Deterministic seed so demo runs are reproducible between resets.
_RNG_SEED = 20260901


DEMO_CUSTOMERS: list[dict] = [
    {
        "name": "Rahul Sharma",
        "email": "rahul.sharma@example.com",
        "phone": "+91 98200 11223",
        "lifetime_value": 2_500_000,  # ₹25,000
        "subscription_status": SubscriptionStatus.ACTIVE,
        "days_until_cancellation": 5,
        "is_business": False,
    },
    {
        "name": "Aman Verma",
        "email": "aman.verma@example.com",
        "phone": "+91 99300 44556",
        "lifetime_value": 8_400_000,  # ₹84,000
        "subscription_status": SubscriptionStatus.ACTIVE,
        "days_until_cancellation": 2,
        "is_business": False,
    },
    {
        "name": "Neha Singh",
        "email": "neha.singh@example.com",
        "phone": "+91 97400 77889",
        "lifetime_value": 450_000,  # ₹4,500
        "subscription_status": SubscriptionStatus.NONE,
        "days_until_cancellation": None,
        "is_business": False,
    },
    {
        "name": "Acme Corp",
        "email": "accounts@acmecorp.example.com",
        "phone": "+91 22 4000 1200",
        "lifetime_value": 42_000_000,  # ₹4,20,000
        "subscription_status": SubscriptionStatus.ACTIVE,
        "days_until_cancellation": 12,
        "is_business": True,
    },
    {
        "name": "Priya Nair",
        "email": "priya.nair@example.com",
        "phone": "+91 96500 33221",
        "lifetime_value": 1_200_000,  # ₹12,000
        "subscription_status": SubscriptionStatus.PAST_DUE,
        "days_until_cancellation": 1,
        "is_business": False,
    },
    {
        "name": "Vikram Desai",
        "email": "vikram.desai@example.com",
        "phone": "+91 90040 55667",
        "lifetime_value": 6_750_000,  # ₹67,500
        "subscription_status": SubscriptionStatus.ACTIVE,
        "days_until_cancellation": 21,
        "is_business": False,
    },
    {
        "name": "Sana Qureshi",
        "email": "sana.qureshi@example.com",
        "phone": "+91 93100 99887",
        "lifetime_value": 320_000,  # ₹3,200
        "subscription_status": SubscriptionStatus.CANCELLED,
        "days_until_cancellation": None,
        "is_business": False,
    },
    {
        "name": "Zenith Logistics",
        "email": "finance@zenithlogistics.example.com",
        "phone": "+91 80 2233 4455",
        "lifetime_value": 18_500_000,  # ₹1,85,000
        "subscription_status": SubscriptionStatus.ACTIVE,
        "days_until_cancellation": 30,
        "is_business": True,
    },
]

#: Plausible subscription/invoice amounts in paise.
_TYPICAL_AMOUNTS = [
    49_900,  # ₹499
    99_900,  # ₹999
    149_900,  # ₹1,499
    299_900,  # ₹2,999
    499_900,  # ₹4,999
    899_900,  # ₹8,999
]
_BUSINESS_AMOUNTS = [
    2_500_000,  # ₹25,000
    4_500_000,  # ₹45,000
    8_500_000,  # ₹85,000
]

_HISTORY_FAILURE_REASONS = [
    FailureReason.EXPIRED_CARD,
    FailureReason.INSUFFICIENT_FUNDS,
    FailureReason.TEMPORARY_BANK_FAILURE,
    FailureReason.CARD_DECLINED,
]


def reset_demo_data(db: Session) -> None:
    """Delete all application data.

    Ordered child-first so the delete works even where the database does not
    cascade for us.
    """
    for model in (Message, AgentAction, RecoveryCase, Transaction, Customer):
        db.query(model).delete(synchronize_session=False)
    db.commit()


def seed_demo_data(db: Session, *, reset: bool = True) -> dict[str, int]:
    """Populate demo customers and their transaction history.

    Returns a count summary. Seeds only *history* — no open recovery cases —
    so the demo starts from a clean slate and every case a judge sees was
    genuinely produced by the workflow rather than inserted by the seeder.
    """
    if reset:
        reset_demo_data(db)

    rng = random.Random(_RNG_SEED)
    now = utcnow()

    customers: list[Customer] = []
    for spec in DEMO_CUSTOMERS:
        customer = Customer(
            name=spec["name"],
            email=spec["email"],
            phone=spec["phone"],
            lifetime_value=spec["lifetime_value"],
            subscription_status=spec["subscription_status"],
            days_until_cancellation=spec["days_until_cancellation"],
            is_business=spec["is_business"],
            created_at=now - timedelta(days=rng.randint(120, 900)),
        )
        db.add(customer)
        customers.append(customer)
    db.flush()

    transaction_count = 0
    for customer in customers:
        amounts = _BUSINESS_AMOUNTS if customer.is_business else _TYPICAL_AMOUNTS
        base_amount = rng.choice(amounts)

        # Six months of monthly billing history per customer, with occasional
        # failures so failure-reason analytics are not empty on first load.
        for months_ago in range(6, 0, -1):
            failed = rng.random() < 0.18
            reason = rng.choice(_HISTORY_FAILURE_REASONS) if failed else None
            db.add(
                Transaction(
                    customer_id=customer.id,
                    amount=base_amount,
                    currency="INR",
                    status=(
                        TransactionStatus.FAILED if failed else TransactionStatus.SUCCESS
                    ),
                    failure_reason=reason.value if reason else None,
                    attempt_number=1,
                    created_at=now - timedelta(days=months_ago * 30, hours=rng.randint(0, 20)),
                )
            )
            transaction_count += 1

    db.commit()
    return {"customers": len(customers), "transactions": transaction_count}
