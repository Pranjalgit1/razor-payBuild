"""Strict decision and bounded Claude tool-loop tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.anthropic_provider import AnthropicAgentProvider
from app.agents.base import AgentInvalidDecision
from app.agents.schemas import AgentCaseContext, AgentDecision
from app.models.enums import CaseStatus, CaseType, RiskLevel


def _context() -> AgentCaseContext:
    return AgentCaseContext(
        case_id=1,
        customer_id=1,
        transaction_id=1,
        case_type=CaseType.FAILED_PAYMENT,
        status=CaseStatus.DETECTED,
        amount_at_risk=100_000,
        risk_score=45,
        risk_level=RiskLevel.MEDIUM,
        risk_factors=[],
        retry_count=0,
        reminder_count=0,
        has_scheduled_retry=False,
        policy_limits={
            "max_payment_retries": 2,
            "max_reminders": 3,
            "contact_cooldown_hours": 24,
            "escalation_amount_threshold": 5_000_000,
            "high_value_ltv_threshold": 5_000_000,
        },
    )


def _tool_use(name: str, tool_input: dict, identifier: str = "tool-1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=identifier)


class FakeTools:
    def __init__(self):
        self.calls = []

    def invoke(self, name, arguments):
        self.calls.append((name, arguments))
        return {"id": 1, "status": "failed"}


class FakeMessages:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.responses)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_agent_decision_forbids_extra_or_invalid_fields():
    valid = {
        "diagnosis": "expired_card",
        "confidence": 0.94,
        "recommended_action": "generate_payment_link",
        "reason": "The card must be updated before payment can succeed.",
        "escalation_required": False,
    }
    assert AgentDecision.model_validate(valid).confidence == 0.94

    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**valid, "hidden_reasoning": "secret"})
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**valid, "confidence": 1.1})
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**valid, "confidence": "0.94"})
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**valid, "escalation_required": "false"})
    with pytest.raises(ValidationError):
        AgentDecision.model_validate({**valid, "recommended_action": "wire_money"})


def test_anthropic_provider_uses_read_tool_then_strict_submission():
    investigation = SimpleNamespace(
        id="msg-1",
        model="claude-opus-5",
        content=[_tool_use("get_customer", {}, "read-1")],
    )
    submission = SimpleNamespace(
        id="msg-2",
        model="claude-opus-5",
        content=[
            _tool_use(
                "submit_recovery_decision",
                {
                    "diagnosis": "expired_card",
                    "confidence": 0.94,
                    "recommended_action": "generate_payment_link",
                    "reason": "The expired card requires a secure payment-method update link.",
                    "escalation_required": False,
                },
                "submit-1",
            )
        ],
    )
    client = FakeClient([investigation, submission])
    tools = FakeTools()
    provider = AnthropicAgentProvider(
        api_key="unused",
        model="claude-opus-5",
        client=client,
    )

    result = provider.decide(_context(), tools)

    assert result.decision.recommended_action.value == "generate_payment_link"
    assert result.metadata.provider == "anthropic"
    assert result.metadata.tool_calls == ("get_customer", "submit_recovery_decision")
    assert tools.calls == [("get_customer", {})]
    assert len(client.messages.requests) == 2
    assert client.messages.requests[0]["tool_choice"] == {"type": "any"}
    assert all(tool["strict"] is True for tool in client.messages.requests[0]["tools"])


def test_anthropic_provider_rejects_malformed_submission_without_coercion():
    response = SimpleNamespace(
        id="msg-bad",
        model="claude-opus-5",
        content=[
            _tool_use(
                "submit_recovery_decision",
                {
                    "diagnosis": "expired_card",
                    "confidence": 7,
                    "recommended_action": "generate_payment_link",
                    "reason": "Invalid confidence must not be coerced or silently replaced.",
                    "escalation_required": False,
                },
            )
        ],
    )
    provider = AnthropicAgentProvider(
        api_key="unused",
        model="claude-opus-5",
        client=FakeClient([response]),
    )

    with pytest.raises(AgentInvalidDecision):
        provider.decide(_context(), FakeTools())


def test_anthropic_provider_rejects_mixed_or_duplicate_final_submissions():
    valid = {
        "diagnosis": "expired_card",
        "confidence": 0.94,
        "recommended_action": "generate_payment_link",
        "reason": "The expired card requires a secure payment-method update link.",
        "escalation_required": False,
    }
    mixed = SimpleNamespace(
        id="mixed",
        model="claude-opus-5",
        content=[
            _tool_use("get_customer", {}, "read"),
            _tool_use("submit_recovery_decision", valid, "submit"),
        ],
    )
    duplicate = SimpleNamespace(
        id="duplicate",
        model="claude-opus-5",
        content=[
            _tool_use("submit_recovery_decision", valid, "submit-1"),
            _tool_use("submit_recovery_decision", valid, "submit-2"),
        ],
    )

    for response in (mixed, duplicate):
        provider = AnthropicAgentProvider(
            api_key="unused",
            model="claude-opus-5",
            client=FakeClient([response]),
        )
        with pytest.raises(AgentInvalidDecision):
            provider.decide(_context(), FakeTools())


def test_anthropic_provider_enforces_total_tool_call_limit():
    response = SimpleNamespace(
        id="too-many",
        model="claude-opus-5",
        content=[
            _tool_use("get_customer", {}, "one"),
            _tool_use("get_transaction", {}, "two"),
        ],
    )
    provider = AnthropicAgentProvider(
        api_key="unused",
        model="claude-opus-5",
        max_tool_calls=1,
        client=FakeClient([response]),
    )
    with pytest.raises(AgentInvalidDecision):
        provider.decide(_context(), FakeTools())


def test_provider_selection_and_runtime_availability_fallback():
    from app.agents.base import AgentProviderUnavailable
    from app.agents.factory import (
        AgentConfigurationError,
        AvailabilityFallbackProvider,
        build_agent_provider,
    )
    from app.agents.schemas import (
        CustomerToolResult,
        PaymentStatusToolResult,
        TransactionToolResult,
    )
    from app.config import Settings

    assert type(build_agent_provider(Settings(ai_provider="rules"))).__name__ == "RulesAgentProvider"
    missing_key = build_agent_provider(
        Settings(ai_provider="anthropic", anthropic_api_key=None)
    )
    assert type(missing_key).__name__ == "RulesAgentProvider"

    class UnavailableProvider:
        name = "anthropic"

        def decide(self, context, tools):
            raise AgentProviderUnavailable("timeout")

    tools = SimpleNamespace(
        get_customer=lambda: CustomerToolResult(
            id=1,
            lifetime_value=100_000,
            subscription_status="none",
            days_until_cancellation=None,
            is_business=False,
            has_email=True,
            has_phone=False,
        ),
        get_transaction=lambda: TransactionToolResult(
            id=1,
            customer_id=1,
            amount=100_000,
            currency="INR",
            status="failed",
            failure_reason="expired_card",
            attempt_number=1,
            parent_transaction_id=None,
            is_historical=False,
        ),
        get_payment_history=lambda limit=10: [],
        check_payment_status=lambda: PaymentStatusToolResult(
            transaction_id=1,
            status="failed",
            failure_reason="expired_card",
        ),
    )
    result = AvailabilityFallbackProvider(UnavailableProvider()).decide(
        _context(), tools
    )
    assert result.metadata.provider == "rules"
    assert result.metadata.configured_provider == "anthropic"
    assert result.metadata.fallback_reason == "provider_unavailable:timeout"

    with pytest.raises(AgentConfigurationError):
        build_agent_provider(Settings(ai_provider="typo"))


def test_read_tool_rejects_coercive_history_limits():
    from app.agents.tools import ReadOnlyAgentTools

    tools = object.__new__(ReadOnlyAgentTools)
    for invalid in ("5", True, 5.0, None):
        with pytest.raises(AgentInvalidDecision):
            tools.invoke("get_payment_history", {"limit": invalid})
