"""Developer agent: implements code changes using Anthropic tool-use loop."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, Attempt, TaskStatus, CriterionStatus
from core.board import MessageBoard
from core.logger import RunLogger
from tools.file_tools import read_file, edit_file, search_code, list_files
from tools.command_tool import run_command
from tools.git_tools import git_diff
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Developer agent in DevPilot.

Your job is to implement code changes to satisfy the given criteria and tasks.

Rules:
1. Read the repo's AGENTS.md and follow the style conventions there.
2. NEVER repeat an attempt that is already listed in attempts[]. Choose a different approach.
3. Record every attempt you make (what you tried, what happened).
4. When you edit code, always read the file first to understand current state.
5. After editing, check if there's a test command you should run.
6. If you see a TEST_FAILURE or VERIFY_FINDING message, fix the EXACT issue described.
7. If you see a REVIEW_ISSUE message, either fix it or post a DEV_REPLY with evidence.
8. Never modify files outside the workspace.
9. If you discover work the plan missed, note it clearly in your response.
10. Use Decimal for all money calculations, never bare float arithmetic.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read the content of a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Write content to a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern in Python files within the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text pattern to search"},
                "file_glob": {"type": "string", "description": "File glob, default *.py"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_glob": {"type": "string", "description": "Glob pattern, default *"}
            },
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "Run an allowed command (pytest, python, ls, cat, git diff, git status).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
                "cwd": {"type": "string", "description": "Working directory (optional)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "git_diff",
        "description": "Get the diff between original repo and workspace.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class DeveloperAgent:
    """Tool-using developer agent that implements code changes."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("MODEL", "claude-opus-4-5")
        self.agent_name = "developer"

    def _build_user_message(self) -> str:
        """Build the user message describing current tasks, criteria, and messages."""
        workspace = self.state.workspace_path
        parts = ["## Current Tasks\n"]
        for task in self.state.tasks:
            if task.status not in ("done", "blocked"):
                parts.append(f"- [{task.status}] {task.id}: {task.text}")

        parts.append("\n## Acceptance Criteria\n")
        for c in self.state.criteria:
            parts.append(f"- [{c.status}] {c.id}: {c.text}")

        # Messages addressed to developer
        my_msgs = self.board.read_for(self.agent_name)
        if my_msgs:
            parts.append("\n## Messages For You\n")
            for m in my_msgs:
                parts.append(f"**{m.type}** from {m.sender}:")
                for k, v in m.payload.items():
                    parts.append(f"  {k}: {v}")

        # Past attempts
        if self.state.attempts:
            parts.append("\n## Past Attempts (DO NOT REPEAT)\n")
            for a in self.state.attempts:
                parts.append(f"- {a.agent}: tried '{a.what_was_tried}' -> {a.result}")

        parts.append(f"\n## Workspace Path\n{workspace}")
        parts.append(f"\n## Request\n{self.state.request}")
        return "\n".join(parts)

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return its result as a string."""
        ws = self.state.workspace_path

        try:
            if tool_name == "read_file":
                path = str(Path(ws) / tool_input["path"])
                result = read_file(path, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                input_summary=tool_input["path"], output_summary=result[:100])
                return result

            elif tool_name == "edit_file":
                path = str(Path(ws) / tool_input["path"])
                edit_file(path, tool_input["content"], ws)
                attempt_summary = f"edited {tool_input['path']}"
                self.state.attempts.append(Attempt(
                    agent=self.agent_name,
                    what_was_tried=attempt_summary,
                    result="pending verification"
                ))
                self.logger.log(self.agent_name, "TOOL_CALL", tool="edit_file",
                                input_summary=tool_input["path"], output_summary="written")
                return f"File written: {tool_input['path']}"

            elif tool_name == "search_code":
                glob = tool_input.get("file_glob", "*.py")
                results = search_code(tool_input["pattern"], ws, glob)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="search_code",
                                input_summary=tool_input["pattern"],
                                output_summary=f"{len(results)} matches")
                return json.dumps(results[:20])

            elif tool_name == "list_files":
                glob = tool_input.get("file_glob", "*")
                files = list_files(ws, glob)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="list_files",
                                input_summary=glob, output_summary=str(files[:10]))
                return "\n".join(files)

            elif tool_name == "run_command":
                cmd = tool_input["command"]
                cwd = tool_input.get("cwd")
                result = run_command(cmd, ws, cwd, self.state.simulate_missing)
                output = result["stdout"] + result["stderr"]
                if result["blocked"]:
                    self.logger.log(self.agent_name, "BLOCKED", tool="run_command",
                                    input_summary=cmd, output_summary=result["error"])
                    return f"BLOCKED: {result['error']}"
                self.logger.log(self.agent_name, "TOOL_CALL", tool="run_command",
                                input_summary=cmd, output_summary=output[:200])
                return f"exit_code={result['exit_code']}\n{output}"

            elif tool_name == "git_diff":
                diff = git_diff(self.state.repo_path, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="git_diff",
                                input_summary="", output_summary=diff[:100])
                return diff or "(no differences)"

        except SafetyError as exc:
            self.logger.log(self.agent_name, "BLOCKED", tool=tool_name,
                            input_summary=str(tool_input), output_summary=str(exc))
            return f"BLOCKED by safety layer: {exc}"
        except Exception as exc:
            self.logger.log(self.agent_name, "TOOL_ERROR", tool=tool_name,
                            input_summary=str(tool_input), output_summary=str(exc))
            return f"ERROR: {exc}"

        return "ERROR: unknown tool"

    def run(self) -> str:
        """Run the developer agent loop. Returns a summary of what was done."""
        self.logger.log(self.agent_name, "AGENT_START", input_summary=self.state.request)

        # Count steps
        agent_key = self.agent_name
        if agent_key not in self.state.steps_per_agent:
            self.state.steps_per_agent[agent_key] = 0

        messages = [{"role": "user", "content": self._build_user_message()}]
        max_iterations = min(
            20,
            self.state.max_steps_per_agent - self.state.steps_per_agent[agent_key]
        )

        plan_gap_posted = False
        final_summary = ""

        for _iteration in range(max_iterations):
            self.state.steps_per_agent[agent_key] = self.state.steps_per_agent.get(agent_key, 0) + 1

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Collect text and tool calls
            tool_calls = []
            text_parts = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(block)

            assistant_text = "\n".join(text_parts)
            if assistant_text:
                final_summary = assistant_text

            # Check for PLAN_GAP signal in assistant text
            if "PLAN_GAP" in assistant_text and not plan_gap_posted:
                self.board.post("PLAN_GAP", self.agent_name, "planner",
                                {"description": assistant_text[:500]})
                plan_gap_posted = True

            # If no tool calls, we're done
            if not tool_calls:
                self.logger.log(self.agent_name, "AGENT_DONE",
                                output_summary=assistant_text[:200])
                break

            # Add assistant response to messages
            messages.append({"role": "assistant", "content": response.content})

            # Execute tool calls and collect results
            tool_results = []
            for tc in tool_calls:
                result_content = self._dispatch_tool(tc.name, tc.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_content,
                })

            messages.append({"role": "user", "content": tool_results})

            # Check stop condition
            if response.stop_reason == "end_turn":
                self.logger.log(self.agent_name, "AGENT_DONE",
                                output_summary="end_turn reached")
                break

        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=final_summary[:200])
        return final_summary
