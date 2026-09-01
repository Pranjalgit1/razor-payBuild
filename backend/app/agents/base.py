"""Provider abstraction and safe agent-run metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.agents.schemas import AgentCaseContext, AgentDecision

if TYPE_CHECKING:
    from app.agents.tools import ReadOnlyAgentTools


class AgentError(Exception):
    """Base class for provider and decision failures."""


class AgentProviderUnavailable(AgentError):
    """A configured provider could not be reached or used."""


class AgentInvalidDecision(AgentError):
    """A provider returned malformed output or violated the tool contract."""


@dataclass(frozen=True, slots=True)
class AgentRunMetadata:
    provider: str
    configured_provider: str
    model: str | None = None
    request_id: str | None = None
    fallback_reason: str | None = None
    tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentProviderResult:
    decision: AgentDecision
    metadata: AgentRunMetadata


class AgentProvider(Protocol):
    name: str

    def decide(
        self,
        context: AgentCaseContext,
        tools: "ReadOnlyAgentTools",
    ) -> AgentProviderResult: ...
