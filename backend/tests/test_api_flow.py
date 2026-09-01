"""End-to-end API flow test for Phase 1.

Exercises the whole path a demo takes: seed → simulate a failed payment →
a recovery case is opened automatically → the audit trail records it → the
case is readable through every endpoint that will back the UI.

Run with:  python -m pytest tests -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway database before any app module is imported,
# since settings are read at import time.
_TMP_DB = Path(tempfile.gettempdir()) / "revenuerecover_test.db"
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_TMP_DB.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import entities  # noqa: E402,F401


@pytest.fixture(scope="module")
def client():
    _TMP_DB.unlink(missing_ok=True)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    engine.dispose()
    _TMP_DB.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def seeded(client):
    response = client.post("/api/demo/seed")
    assert response.status_code == 200, response.text
    return response.json()["detail"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_seed_creates_customers_and_transactions(seeded):
    assert seeded["customers"] == 8
    assert seeded["transactions"] == 48  # 8 customers x 6 months


def test_customers_are_listed_with_formatted_currency(client, seeded):
    response = client.get("/api/customers")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 8

    rahul = next(c for c in body["items"] if c["name"] == "Rahul Sharma")
    assert rahul["lifetime_value"] == 2_500_000  # paise
    assert rahul["lifetime_value_formatted"] == "₹25,000"


def test_indian_digit_grouping(client, seeded):
    """Lakh-scale amounts must group as 4,20,000 — not 420,000."""
    response = client.get("/api/customers", params={"search": "acme"})
    acme = response.json()["items"][0]
    assert acme["lifetime_value_formatted"] == "₹4,20,000"


def test_successful_payment_opens_no_case(client, seeded):
    customer_id = client.get("/api/customers").json()["items"][0]["id"]

    response = client.post(
        "/api/payments/simulate",
        json={"customer_id": customer_id, "amount": 99_900, "succeed": True},
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["transaction"]["status"] == "success"
    assert body["transaction"]["failure_reason"] is None
    assert body["recovery_case"] is None


def test_failed_payment_opens_a_recovery_case(client, seeded):
    """The core Phase 1 acceptance: a failure automatically becomes a case."""
    customers = client.get("/api/customers", params={"search": "rahul"}).json()["items"]
    rahul = customers[0]

    response = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": rahul["id"],
            "amount": 299_900,  # ₹2,999
            "succeed": False,
            "failure_reason": "expired_card",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["transaction"]["status"] == "failed"
    assert body["transaction"]["failure_reason"] == "expired_card"
    assert body["transaction"]["amount_formatted"] == "₹2,999"

    case = body["recovery_case"]
    assert case is not None
    assert case["status"] == "detected"
    assert case["amount_at_risk"] == 299_900
    assert case["amount_at_risk_formatted"] == "₹2,999"
    assert case["amount_recovered"] == 0
    # Rahul has an active subscription, so this is a subscription failure.
    assert case["case_type"] == "failed_subscription"
    # Risk is now calculated by deterministic Phase 2 rules; AI diagnosis
    # remains unset until the separate decision layer runs.
    assert case["risk_score"] == 51
    assert case["risk_level"] == "medium"
    assert len(case["risk_factors"]) == 7
    assert case["diagnosis"] is None

    pytest.case_id = case["id"]


def test_case_detail_includes_audit_trail(client, seeded):
    case_id = pytest.case_id

    response = client.get(f"/api/recovery-cases/{case_id}")
    assert response.status_code == 200, response.text
    detail = response.json()

    assert detail["customer"]["name"] == "Rahul Sharma"
    assert detail["transaction"]["amount"] == 299_900

    # PRD rule 6: every recovery case has an audit trail.
    assert len(detail["actions"]) >= 1
    first = detail["actions"][0]
    assert first["action_type"] == "revenue_at_risk_detected"
    assert first["status"] == "success"
    assert "expired card" in first["reasoning"]
    assert first["details"]["amount_at_risk"] == 299_900

    scoring = next(a for a in detail["actions"] if a["action_type"] == "risk_score_calculated")
    assert scoring["details"]["engine"] == "rule_based"
    assert scoring["details"]["score"] == detail["risk_score"]
    assert len(scoring["details"]["factors"]) == 7


def test_agent_activity_feed_shows_the_action(client, seeded):
    response = client.get("/api/agent/actions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert any(a["action_type"] == "revenue_at_risk_detected" for a in body["items"])


def test_checkout_abandonment_is_classified_separately(client, seeded):
    neha = client.get("/api/customers", params={"search": "neha"}).json()["items"][0]

    response = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": neha["id"],
            "amount": 149_900,
            "succeed": False,
            "failure_reason": "checkout_abandoned",
        },
    )
    body = response.json()
    assert body["transaction"]["status"] == "abandoned"
    assert body["recovery_case"]["case_type"] == "checkout_abandonment"


def test_business_customer_routes_to_invoice_recovery(client, seeded):
    acme = client.get("/api/customers", params={"search": "acme"}).json()["items"][0]

    response = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": acme["id"],
            "amount": 8_500_000,  # ₹85,000
            "succeed": False,
            "failure_reason": "insufficient_funds",
        },
    )
    body = response.json()
    assert body["recovery_case"]["case_type"] == "overdue_invoice"
    assert body["recovery_case"]["amount_at_risk_formatted"] == "₹85,000"


def test_case_list_filters(client, seeded):
    all_cases = client.get("/api/recovery-cases").json()
    assert all_cases["total"] >= 3

    detected = client.get("/api/recovery-cases", params={"status": "detected"}).json()
    assert detected["total"] == all_cases["total"]

    recovered = client.get("/api/recovery-cases", params={"status": "recovered"}).json()
    assert recovered["total"] == 0  # nothing is recovered until Phase 5

    large = client.get("/api/recovery-cases", params={"min_amount": 1_000_000}).json()
    assert large["total"] == 1
    assert large["items"][0]["customer"]["name"] == "Acme Corp"

    by_type = client.get(
        "/api/recovery-cases", params={"case_type": "checkout_abandonment"}
    ).json()
    assert by_type["total"] == 1


def test_case_list_rows_carry_the_customer(client, seeded):
    """The Recovery Cases table needs the customer name in one round trip."""
    rows = client.get("/api/recovery-cases").json()["items"]
    assert all(row["customer"]["name"] for row in rows)


def test_simulating_payment_for_unknown_customer_404s(client, seeded):
    response = client.post(
        "/api/payments/simulate",
        json={"customer_id": 999_999, "amount": 10_000, "succeed": False},
    )
    assert response.status_code == 404


def test_rejects_non_positive_amount(client, seeded):
    customer_id = client.get("/api/customers").json()["items"][0]["id"]
    response = client.post(
        "/api/payments/simulate",
        json={"customer_id": customer_id, "amount": 0, "succeed": False},
    )
    assert response.status_code == 422


def test_unknown_case_404s(client, seeded):
    assert client.get("/api/recovery-cases/999999").status_code == 404


def test_reset_returns_demo_to_known_state(client, seeded):
    assert client.get("/api/recovery-cases").json()["total"] > 0

    response = client.post("/api/demo/reset")
    assert response.status_code == 200

    assert client.get("/api/recovery-cases").json()["total"] == 0
    assert client.get("/api/agent/actions").json()["total"] == 0
    assert client.get("/api/customers").json()["total"] == 8


def test_bounded_action_can_recover_revenue_with_complete_audit(client, seeded):
    neha = client.get("/api/customers", params={"search": "neha"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": neha["id"],
            "amount": 149_900,
            "succeed": False,
            "failure_reason": "expired_card",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    action = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "generate_payment_link"},
    )
    assert action.status_code == 200, action.text
    assert action.json()["policy"]["allowed"] is True
    assert action.json()["case"]["status"] == "verifying"
    assert action.json()["details"]["payment_link"].endswith(f"/{case_id}")

    payment = client.post(
        f"/api/recovery-cases/{case_id}/simulate-payment",
        json={"succeed": True},
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["case"]["status"] == "recovered"
    assert payment.json()["case"]["amount_recovered"] == 149_900

    detail = client.get(f"/api/recovery-cases/{case_id}").json()
    action_types = [entry["action_type"] for entry in detail["actions"]]
    assert "recovery_action_approved" in action_types
    assert "recovery_action_executed" in action_types
    assert "recovery_payment_verified" in action_types


def test_high_value_action_is_blocked_logged_and_escalated(client, seeded):
    acme = client.get("/api/customers", params={"search": "acme"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": acme["id"],
            "amount": 8_500_000,
            "succeed": False,
            "failure_reason": "insufficient_funds",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    response = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "generate_payment_link"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["policy"] == {
        "allowed": False,
        "code": "amount_requires_escalation",
        "reason": "The amount at risk meets the mandatory human-escalation threshold.",
        "escalation_required": True,
    }
    assert body["case"]["status"] == "escalated"
    assert body["case"]["action_taken"] == "escalate_to_human"

    detail = client.get(f"/api/recovery-cases/{case_id}").json()
    blocked = next(
        entry for entry in detail["actions"]
        if entry["action_type"] == "recovery_action_blocked"
    )
    assert blocked["status"] == "blocked"
    assert blocked["details"]["policy_code"] == "amount_requires_escalation"
    assert any(
        entry["action_type"] == "recovery_escalated"
        for entry in detail["actions"]
    )


def test_contact_cooldown_blocks_duplicate_reminder(client, seeded):
    priya = client.get("/api/customers", params={"search": "priya"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": priya["id"],
            "amount": 99_900,
            "succeed": False,
            "failure_reason": "expired_card",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    first = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "send_email"},
    )
    assert first.status_code == 200
    assert first.json()["policy"]["allowed"] is True
    assert first.json()["case"]["reminder_count"] == 1

    second = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "send_email"},
    )
    assert second.status_code == 200
    assert second.json()["policy"]["allowed"] is False
    assert second.json()["policy"]["code"] == "contact_cooldown"
    assert second.json()["audit_action"]["status"] == "blocked"


def test_same_failed_retry_is_not_repeated(client, seeded):
    sana = client.get("/api/customers", params={"search": "sana"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": sana["id"],
            "amount": 49_900,
            "succeed": False,
            "failure_reason": "network_error",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    retry = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "retry_payment"},
    )
    assert retry.status_code == 200
    retry_body = retry.json()
    assert retry_body["policy"]["allowed"] is True
    assert retry_body["executed"] is True
    assert retry_body["case"]["retry_count"] == 1
    retry_transaction_id = retry_body["details"]["retry_transaction_id"]

    failed = client.post(
        f"/api/recovery-cases/{case_id}/simulate-payment",
        json={"succeed": False, "failure_reason": "network_error"},
    )
    assert failed.status_code == 201
    assert failed.json()["transaction"]["id"] == retry_transaction_id
    assert failed.json()["transaction"]["status"] == "failed"
    assert failed.json()["case"]["amount_recovered"] == 0

    repeated = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "retry_payment"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["policy"]["allowed"] is False
    assert repeated.json()["policy"]["code"] == "repeated_failed_action"
    assert repeated.json()["case"]["status"] == "escalated"


def test_scheduled_retry_is_durable_and_cannot_run_early(client, seeded):
    neha = client.get("/api/customers", params={"search": "neha"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": neha["id"],
            "amount": 99_900,
            "succeed": False,
            "failure_reason": "temporary_bank_failure",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    scheduled = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "schedule_retry"},
    )
    assert scheduled.status_code == 200
    body = scheduled.json()
    assert body["executed"] is True
    assert body["case"]["scheduled_retry_at"] is not None
    assert body["details"]["scheduled_for"] == body["case"]["scheduled_retry_at"]

    early = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "retry_payment"},
    )
    assert early.status_code == 200
    assert early.json()["executed"] is False
    assert early.json()["policy"]["code"] == "retry_not_due"

    duplicate = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "schedule_retry"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["policy"]["code"] == "retry_already_scheduled"


def test_terminal_case_rejects_further_actions(client, seeded):
    neha = client.get("/api/customers", params={"search": "neha"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": neha["id"],
            "amount": 49_900,
            "succeed": False,
            "failure_reason": "expired_card",
        },
    ).json()
    case_id = created["recovery_case"]["id"]
    client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "generate_payment_link"},
    )
    paid = client.post(
        f"/api/recovery-cases/{case_id}/simulate-payment",
        json={"succeed": True},
    )
    assert paid.json()["case"]["status"] == "recovered"

    blocked = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "send_email"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["executed"] is False
    assert blocked.json()["policy"]["code"] == "terminal_case"


def test_execution_failure_is_audited_without_partial_state(client, seeded, monkeypatch):
    neha = client.get("/api/customers", params={"search": "neha"}).json()["items"][0]
    created = client.post(
        "/api/payments/simulate",
        json={
            "customer_id": neha["id"],
            "amount": 79_900,
            "succeed": False,
            "failure_reason": "expired_card",
        },
    ).json()
    case_id = created["recovery_case"]["id"]

    import app.workflow.recovery_workflow as workflow_module

    def fail_execution(*args, **kwargs):
        case = args[1]
        case.status = "executing"
        case.action_taken = "generate_payment_link"
        raise RuntimeError("simulated executor failure")

    monkeypatch.setattr(workflow_module, "execute_action", fail_execution)
    response = client.post(
        f"/api/recovery-cases/{case_id}/execute",
        json={"action": "generate_payment_link"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["policy"]["allowed"] is True
    assert body["executed"] is False
    assert body["audit_action"]["status"] == "failed"
    assert body["case"]["status"] == "detected"
    assert body["case"]["action_taken"] is None

    detail = client.get(f"/api/recovery-cases/{case_id}").json()
    assert detail["status"] == "detected"
    assert detail["action_taken"] is None
    assert any(
        entry["action_type"] == "recovery_action_failed"
        for entry in detail["actions"]
    )
