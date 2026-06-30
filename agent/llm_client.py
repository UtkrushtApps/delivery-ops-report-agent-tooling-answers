"""Real-model client wrapper built on LiteLLM.

In normal operation this calls a real provider model to plan tool usage.
In AGENT_TEST_MODE (no key required) it must not perform a network call.
"""
import json
from typing import Any, Dict, List

import litellm

from .config import config


class LLMClient:
    def __init__(self, model: str | None = None):
        self.model = model or config.AGENT_MODEL

    def plan_tool_calls(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ask the model to choose a tool call given the conversation and tool specs.

        Returns the raw assistant message dict (which may include tool_calls).
        Real network call; requires a provider key.
        """
        if config.AGENT_TEST_MODE:
            raise RuntimeError(
                "LLMClient.plan_tool_calls called in AGENT_TEST_MODE; "
                "end-to-end planning requires a provider key."
            )
        resp = litellm.completion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        return resp["choices"][0]["message"]

    def synthesize(self, messages: List[Dict[str, Any]]) -> str:
        """Produce the final natural-language report from tool results."""
        if config.AGENT_TEST_MODE:
            raise RuntimeError("synthesize called in AGENT_TEST_MODE")
        resp = litellm.completion(
            model=self.model,
            messages=messages,
            temperature=0,
        )
        return resp["choices"][0]["message"]["content"] or ""

    @staticmethod
    def parse_tool_call(message: Dict[str, Any]) -> Dict[str, Any] | None:
        """Extract the first tool call (name + parsed arguments) if present."""
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return None
        call = tool_calls[0]
        fn = call["function"]
        try:
            args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
        except (json.JSONDecodeError, TypeError):
            args = {}
        return {"id": call.get("id"), "name": fn["name"], "arguments": args}

