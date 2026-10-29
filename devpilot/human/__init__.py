"""Human-in-the-loop channels: terminal prompts and a scripted answers file."""

from __future__ import annotations

from devpilot.human.answers import AnswersFileError, AnswersFileHumanChannel
from devpilot.human.console import ConsoleHumanChannel, short_id

__all__ = ["AnswersFileError", "AnswersFileHumanChannel", "ConsoleHumanChannel", "short_id"]
