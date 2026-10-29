from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Msg:
    """Provider-neutral message. role: user | assistant | tool_results."""
    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    results: list[tuple[str, str, str]] = field(default_factory=list)  # (tool_call_id, tool_name, content)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    model: str
    provider: str


class LLMError(Exception):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class BudgetExceeded(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    async def complete(self, *, system: str, messages: list[Msg], tools: list[dict[str, Any]], max_tokens: int,
                       temperature: float, purpose: str) -> LLMResponse: ...


def wire_name(n: str) -> str:
    return n.replace(".", "__")


def tool_name(n: str) -> str:
    return n.replace("__", ".")
