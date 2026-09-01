"""Claude provider using bounded read-only tool calls and a strict final tool."""

from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import ValidationError

from app.agents.base import (
    AgentInvalidDecision,
    AgentProviderResult,
    AgentProviderUnavailable,
    AgentRunMetadata,
)
from app.agents.schemas import AgentCaseContext, AgentDecision
from app.agents.tools import ReadOnlyAgentTools


class AnthropicAgentProvider:
    name = "anthropic"

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
        self._max_tool_turns = max_tool_turns
        self._max_tool_calls = max_tool_calls
        self._client = client or anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=1,
        )

    def decide(
        self,
        context: AgentCaseContext,
        tools: ReadOnlyAgentTools,
    ) -> AgentProviderResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "Investigate this recovery case with the available read-only tools, "
                    "then call submit_recovery_decision exactly once. Return only a concise "
                    "customer-safe reason; never expose hidden reasoning. Case context: "
                    + context.model_dump_json()
                ),
            }
        ]
        called_tools: list[str] = []

        for _ in range(self._max_tool_turns):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=900,
                    system=_SYSTEM_PROMPT,
                    messages=messages,
                    tools=_TOOL_DEFINITIONS,
                    tool_choice={"type": "any"},
                )
            except anthropic.APIError as exc:
                raise AgentProviderUnavailable(type(exc).__name__) from exc
            except (OSError, TimeoutError) as exc:
                raise AgentProviderUnavailable(type(exc).__name__) from exc

            tool_blocks = [
                block
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
            ]
            submissions = [
                block for block in tool_blocks
                if str(block.name) == "submit_recovery_decision"
            ]
            if submissions:
                if len(submissions) != 1 or len(tool_blocks) != 1:
                    raise AgentInvalidDecision(
                        "Claude must submit exactly one final decision without mixed tool calls."
                    )
                submission = submissions[0]
                called_tools.append("submit_recovery_decision")
                if len(called_tools) > self._max_tool_calls:
                    raise AgentInvalidDecision("Claude exceeded the total tool-call limit.")
                try:
                    decision = AgentDecision.model_validate(dict(submission.input or {}))
                except ValidationError as exc:
                    raise AgentInvalidDecision(
                        "Claude returned an invalid structured decision."
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

            assistant_content = [_block_to_dict(block) for block in response.content]
            messages.append({"role": "assistant", "content": assistant_content})
            tool_results: list[dict[str, Any]] = []
            for block in tool_blocks:
                name = str(block.name)
                called_tools.append(name)
                if len(called_tools) > self._max_tool_calls:
                    raise AgentInvalidDecision("Claude exceeded the total tool-call limit.")
                raw_input = dict(block.input or {})
                result = tools.invoke(name, raw_input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, separators=(",", ":")),
                    }
                )

            if not tool_results:
                raise AgentInvalidDecision("Claude did not submit a structured decision.")
            messages.append({"role": "user", "content": tool_results})

        raise AgentInvalidDecision("Claude exceeded the bounded tool-call limit.")


def _block_to_dict(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    if getattr(block, "type", None) == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": dict(block.input or {}),
        }
    return {"type": "text", "text": str(getattr(block, "text", ""))}


_SYSTEM_PROMPT = """You are a revenue recovery decision agent. You may investigate only
through the supplied read-only tools. You cannot execute actions. Choose exactly one
controlled next action and submit it through submit_recovery_decision. Backend policy
is authoritative and may block your proposal. Use no secrets, personal contact data,
or hidden chain-of-thought in the public reason."""

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_customer",
        "description": "Read the current case customer's value tier and account attributes.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_transaction",
        "description": "Read the failed transaction that opened the current recovery case.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_payment_history",
        "description": "Read up to 20 recent payment attempts for this case's customer.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "check_payment_status",
        "description": "Read the current status of the transaction that opened this case.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "submit_recovery_decision",
        "description": "Submit the final validated diagnosis and one proposed controlled action.",
        "input_schema": AgentDecision.model_json_schema(),
        "strict": True,
    },
]
