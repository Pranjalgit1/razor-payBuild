"""Agent provider selection and visible availability fallback."""

from __future__ import annotations

from app.agents.anthropic_provider import AnthropicAgentProvider
from app.agents.base import (
    AgentProvider,
    AgentProviderResult,
    AgentProviderUnavailable,
)
from app.agents.rules import RulesAgentProvider
from app.agents.schemas import AgentCaseContext
from app.agents.tools import ReadOnlyAgentTools
from app.agents.xai_provider import XaiAgentProvider
from app.config import Settings, settings


class AgentConfigurationError(ValueError):
    pass


class AvailabilityFallbackProvider:
    """Fallback only for provider availability; malformed output stays rejected."""

    def __init__(self, primary: AgentProvider) -> None:
        self._primary = primary
        self.name = f"{primary.name}_with_rules_fallback"

    def decide(
        self,
        context: AgentCaseContext,
        tools: ReadOnlyAgentTools,
    ) -> AgentProviderResult:
        try:
            return self._primary.decide(context, tools)
        except AgentProviderUnavailable as exc:
            fallback = RulesAgentProvider(
                configured_provider=self._primary.name,
                fallback_reason=f"provider_unavailable:{exc}",
            )
            return fallback.decide(context, tools)


def build_agent_provider(config: Settings = settings) -> AgentProvider:
    provider_name = config.ai_provider.strip().lower()
    if provider_name == "rules":
        return RulesAgentProvider()

    if provider_name == "anthropic":
        if not config.anthropic_api_key:
            return RulesAgentProvider(
                configured_provider="anthropic",
                fallback_reason="missing_api_key",
            )
        return AvailabilityFallbackProvider(
            AnthropicAgentProvider(
                api_key=config.anthropic_api_key,
                model=_model_for(config, "anthropic"),
                timeout_seconds=config.agent_timeout_seconds,
                max_tool_turns=config.agent_max_tool_turns,
                max_tool_calls=config.agent_max_tool_calls,
            )
        )

    if provider_name in {"xai", "grok"}:
        if not config.xai_api_key:
            return RulesAgentProvider(
                configured_provider="xai",
                fallback_reason="missing_api_key",
            )
        return AvailabilityFallbackProvider(
            XaiAgentProvider(
                api_key=config.xai_api_key,
                model=_model_for(config, "xai"),
                timeout_seconds=config.agent_timeout_seconds,
                max_tool_turns=config.agent_max_tool_turns,
                max_tool_calls=config.agent_max_tool_calls,
            )
        )

    raise AgentConfigurationError(f"Unsupported AI_PROVIDER: {config.ai_provider}")


def _model_for(config: Settings, provider_name: str) -> str:
    override = (config.agent_model or "").strip()
    if override:
        return override
    if provider_name == "xai":
        return config.xai_model.strip() or "grok-4.6"
    return config.anthropic_model.strip() or "claude-opus-5"
