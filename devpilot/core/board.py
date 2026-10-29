"""Message board for inter-agent communication."""

from __future__ import annotations

import uuid
from typing import Any

from core.state import Message


# Valid message types
MESSAGE_TYPES = {
    "PLAN_READY",
    "PLAN_REVISED",
    "CLARIFY",
    "TEST_FAILURE",
    "VERIFY_FINDING",
    "REVIEW_ISSUE",
    "DEV_REPLY",
    "PLAN_GAP",
    "TOOL_UNAVAILABLE",
    "ESCALATE",
}


class MessageBoard:
    """Typed message board for agent-to-agent and agent-to-human communication."""

    def __init__(self):
        """Initialize an empty board."""
        self._messages: list[Message] = []

    def post(
        self,
        msg_type: str,
        sender: str,
        receiver: str,
        payload: dict[str, Any],
    ) -> Message:
        """Post a message and return it."""
        if msg_type not in MESSAGE_TYPES:
            raise ValueError(f"Unknown message type: {msg_type!r}")
        msg = Message(
            type=msg_type,
            sender=sender,
            receiver=receiver,
            payload=payload,
            id=str(uuid.uuid4())[:8],
        )
        self._messages.append(msg)
        return msg

    def read_for(self, agent: str) -> list[Message]:
        """Return all messages addressed to this agent (unread)."""
        return [m for m in self._messages if m.receiver == agent]

    def read_all(self) -> list[Message]:
        """Return all messages on the board."""
        return list(self._messages)

    def has_type(self, msg_type: str, receiver: str | None = None) -> bool:
        """Check if any message of the given type exists (optionally for a receiver)."""
        for m in self._messages:
            if m.type == msg_type:
                if receiver is None or m.receiver == receiver:
                    return True
        return False

    def get_by_type(self, msg_type: str) -> list[Message]:
        """Get all messages of a specific type."""
        return [m for m in self._messages if m.type == msg_type]
