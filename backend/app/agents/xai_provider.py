"""Bounded xAI/Grok structured tool-calling provider."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import monotonic
from typing import Any

import openai
from pydantic import ValidationError

from app.agents.base import (
    AgentInvalidDecision,
    AgentProviderResult,
    AgentProviderUnavailable,
    AgentRunMetadata,
)
from app.agents.schemas import AgentCaseContext, AgentDecision
from app.agents.tools import ReadOnlyAgentTools

_XAI_BASE_URL = "https://api.x.ai/v1"


@dataclass(frozen=True, slots=True)
class _ParsedToolCall:
    identifier: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


class XaiAgentProvider:
    """Use Grok to investigate a case and submit one validated decision."""

    name = "xai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30,
        max_tool_turns: int = 6,
        max_tool_calls: int = 8,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_tool_turns = max_tool_turns
        self._max_tool_calls = max_tool_calls
        self._client = client or openai.OpenAI(
            api_key=api_key,
            base_url=_XAI_BASE_URL,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def decide(
        self,
        context: AgentCaseContext,
        tools: ReadOnlyAgentTools,
    ) -> AgentProviderResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Investigate this recovery case with the available read-only tools, "
                    "then call submit_recovery_decision exactly once. Return only a concise "
                    "customer-safe reason; never expose hidden reasoning. Case context: "
                    + context.model_dump_json()
                ),
            },
        ]
        called_tools: list[str] = []
        deadline = monotonic() + self._timeout_seconds

        for _ in range(self._max_tool_turns):
            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                raise AgentProviderUnavailable("TimeoutError")
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=_TOOL_DEFINITIONS,
                    tool_choice="required",
                    parallel_tool_calls=False,
                    max_completion_tokens=900,
                    timeout=remaining_seconds,
                )
            except (
                openai.APIConnectionError,
                openai.RateLimitError,
                openai.InternalServerError,
            ) as exc:
                raise AgentProviderUnavailable(type(exc).__name__) from exc
            except openai.APIError as exc:
                raise AgentInvalidDecision(
                    "Grok rejected the request; check the API key and model configuration."
                ) from exc
            except (OSError, TimeoutError) as exc:
                raise AgentProviderUnavailable(type(exc).__name__) from exc

            try:
                message = response.choices[0].message
            except (AttributeError, IndexError, TypeError) as exc:
                raise AgentInvalidDecision(
                    "Grok returned an invalid completion response."
                ) from exc

            parsed_calls = [
                _parse_tool_call(call)
                for call in list(getattr(message, "tool_calls", None) or [])
            ]
            if not parsed_calls:
                raise AgentInvalidDecision(
                    "Grok did not call a tool or submit a structured decision."
                )

            submissions = [
                call
                for call in parsed_calls
                if call.name == "submit_recovery_decision"
            ]
            if submissions:
                if len(submissions) != 1 or len(parsed_calls) != 1:
                    raise AgentInvalidDecision(
                        "Grok must submit exactly one final decision without mixed tool calls."
                    )
                called_tools.append("submit_recovery_decision")
                if len(called_tools) > self._max_tool_calls:
                    raise AgentInvalidDecision(
                        "Grok exceeded the total tool-call limit."
                    )
                try:
                    decision = AgentDecision.model_validate(submissions[0].arguments)
                except ValidationError as exc:
                    raise AgentInvalidDecision(
                        "Grok returned an invalid structured decision."
                    ) from exc
                return AgentProviderResult(
                    decision=decision,
                    metadata=AgentRunMetadata(
                        provider=self.name,
                        configured_provider=self.name,
                        model=str(getattr(response, "model", self._model)),
                        request_id=str(getattr(response, "id", "")) or None,
                        tool_calls=tuple(called_tools),
                    ),
                )

            seen_ids: set[str] = set()
            assistant_tool_calls: list[dict[str, Any]] = []
            tool_messages: list[dict[str, Any]] = []
            for call in parsed_calls:
                if call.identifier in seen_ids:
                    raise AgentInvalidDecision("Grok returned duplicate tool-call IDs.")
                seen_ids.add(call.identifier)
                called_tools.append(call.name)
                if len(called_tools) > self._max_tool_calls:
                    raise AgentInvalidDecision(
                        "Grok exceeded the total tool-call limit."
                    )
                result = tools.invoke(call.name, call.arguments)
                assistant_tool_calls.append(
                    {
                        "id": call.identifier,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.raw_arguments,
                        },
                    }
                )
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.identifier,
                        "content": json.dumps(result, separators=(",", ":")),
                    }
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(message, "content", None),
                    "tool_calls": assistant_tool_calls,
                }
            )
            messages.extend(tool_messages)

        raise AgentInvalidDecision("Grok exceeded the bounded tool-call limit.")


def _parse_tool_call(call: Any) -> _ParsedToolCall:
    identifier = str(getattr(call, "id", "")).strip()
    function = getattr(call, "function", None)
    name = str(getattr(function, "name", "")).strip()
    raw_arguments = getattr(function, "arguments", None)
    if not identifier or not name or not isinstance(raw_arguments, str):
        raise AgentInvalidDecision("Grok returned a malformed function call.")
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgentInvalidDecision(
            "Grok returned invalid JSON function arguments."
        ) from exc
    if not isinstance(arguments, dict):
        raise AgentInvalidDecision("Grok function arguments must be an object.")
    return _ParsedToolCall(identifier, name, arguments, raw_arguments)


_SYSTEM_PROMPT = """You are a revenue recovery decision agent. You may investigate only
through the supplied read-only tools. You cannot execute actions. Choose exactly one
controlled next action and submit it through submit_recovery_decision. Backend policy
is authoritative and may block your proposal. Use no secrets, personal contact data,
or hidden chain-of-thought in the public reason."""


def _function_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": True,
        },
    }


_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _function_tool(
        "get_customer",
        "Read the current case customer's value tier and account attributes.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _function_tool(
        "get_transaction",
        "Read the failed transaction that opened the current recovery case.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _function_tool(
        "get_payment_history",
        "Read up to 20 recent payment attempts for this case's customer.",
        {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 20}
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
    ),
    _function_tool(
        "check_payment_status",
        "Read the current status of the transaction that opened this case.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    _function_tool(
        "submit_recovery_decision",
        "Submit the final validated diagnosis and one proposed controlled action.",
        AgentDecision.model_json_schema(),
    ),
]
