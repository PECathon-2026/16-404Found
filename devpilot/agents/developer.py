"""Developer agent — Gemini version."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, Attempt
from core.board import MessageBoard
from core.logger import RunLogger
from core.gemini_client import make_client, get_model_name, run_agent_loop
from tools.file_tools import read_file, edit_file, search_code, list_files
from tools.command_tool import run_command
from tools.git_tools import git_diff
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Developer agent in DevPilot.

Your job is to implement code changes to satisfy the given criteria and tasks.

Rules:
1. Read the repo's AGENTS.md and follow its conventions.
2. NEVER repeat an attempt already listed in attempts[].
3. After editing a file, always record what you tried.
4. When you see TEST_FAILURE or VERIFY_FINDING, fix the exact issue described.
5. When you see REVIEW_ISSUE, fix it or note disagreement.
6. Never modify files outside the workspace.
7. If you discover work the plan missed, clearly say "PLAN_GAP: <description>".
8. Use Decimal for all money calculations, never bare float arithmetic.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Write content to a file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern in Python files within the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "file_glob": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"file_glob": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "Run an allowed command: pytest, python3, ls, cat, git diff, git status.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "git_diff",
        "description": "Get the diff between original repo and workspace.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class DeveloperAgent:
    """Tool-using developer agent (Gemini) that implements code changes."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = make_client()
        self.model = get_model_name()
        self.agent_name = "developer"

    def _build_user_message(self) -> str:
        ws = self.state.workspace_path
        parts = [f"## Request\n{self.state.request}\n", "## Current Tasks\n"]
        for t in self.state.tasks:
            if t.status not in ("done", "blocked"):
                parts.append(f"- [{t.status}] {t.id}: {t.text}")
        parts.append("\n## Acceptance Criteria\n")
        for c in self.state.criteria:
            parts.append(f"- [{c.status}] {c.id}: {c.text}")
        my_msgs = self.board.read_for(self.agent_name)
        if my_msgs:
            parts.append("\n## Messages For You\n")
            for m in my_msgs:
                parts.append(f"**{m.type}** from {m.sender}:")
                for k, v in m.payload.items():
                    parts.append(f"  {k}: {v}")
        if self.state.attempts:
            parts.append("\n## Past Attempts (DO NOT REPEAT)\n")
            for a in self.state.attempts:
                parts.append(f"- {a.agent}: tried '{a.what_was_tried}' -> {a.result}")
        parts.append(f"\n## Workspace\n{ws}")
        return "\n".join(parts)

    def _dispatch(self, tool_name: str, tool_input: dict) -> str:
        ws = self.state.workspace_path
        try:
            if tool_name == "read_file":
                path = str(Path(ws) / tool_input["path"])
                result = read_file(path, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                input_summary=tool_input["path"], output_summary=result[:80])
                return result

            elif tool_name == "edit_file":
                path = str(Path(ws) / tool_input["path"])
                edit_file(path, tool_input["content"], ws)
                self.state.attempts.append(Attempt(
                    agent=self.agent_name,
                    what_was_tried=f"edited {tool_input['path']}",
                    result="pending verification",
                ))
                self.logger.log(self.agent_name, "TOOL_CALL", tool="edit_file",
                                input_summary=tool_input["path"], output_summary="written")
                return f"File written: {tool_input['path']}"

            elif tool_name == "search_code":
                results = search_code(
                    tool_input["pattern"], ws, tool_input.get("file_glob", "*.py")
                )
                self.logger.log(self.agent_name, "TOOL_CALL", tool="search_code",
                                input_summary=tool_input["pattern"],
                                output_summary=f"{len(results)} matches")
                return json.dumps(results[:20])

            elif tool_name == "list_files":
                files = list_files(ws, tool_input.get("file_glob", "*"))
                self.logger.log(self.agent_name, "TOOL_CALL", tool="list_files")
                return "\n".join(files)

            elif tool_name == "run_command":
                cmd = tool_input["command"]
                result = run_command(cmd, ws, tool_input.get("cwd"), self.state.simulate_missing)
                output = result["stdout"] + result["stderr"]
                if result["blocked"]:
                    self.logger.log(self.agent_name, "BLOCKED", tool="run_command",
                                    input_summary=cmd, output_summary=result["error"])
                    return f"BLOCKED: {result['error']}"
                self.logger.log(self.agent_name, "TOOL_CALL", tool="run_command",
                                input_summary=cmd, output_summary=output[:150])
                return f"exit_code={result['exit_code']}\n{output}"

            elif tool_name == "git_diff":
                diff = git_diff(self.state.repo_path, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="git_diff")
                return diff or "(no differences)"

        except SafetyError as exc:
            self.logger.log(self.agent_name, "BLOCKED", tool=tool_name,
                            input_summary=str(tool_input), output_summary=str(exc))
            return f"BLOCKED: {exc}"
        except Exception as exc:
            self.logger.log(self.agent_name, "TOOL_ERROR", tool=tool_name,
                            output_summary=str(exc))
            return f"ERROR: {exc}"
        return "ERROR: unknown tool"

    def run(self) -> str:
        """Run the developer agent loop."""
        self.logger.log(self.agent_name, "AGENT_START", input_summary=self.state.request[:80])
        steps = self.state.steps_per_agent.get(self.agent_name, 0)
        max_iter = min(20, self.state.max_steps_per_agent - steps)

        final = run_agent_loop(
            client=self.client,
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools_config=TOOLS,
            initial_message=self._build_user_message(),
            dispatch_fn=self._dispatch,
            max_iterations=max_iter,
        )

        self.state.steps_per_agent[self.agent_name] = steps + max_iter

        # Check for PLAN_GAP signal
        if "PLAN_GAP" in final:
            self.board.post("PLAN_GAP", self.agent_name, "planner",
                            {"description": final[:500]})

        self.logger.log(self.agent_name, "AGENT_COMPLETE", output_summary=final[:150])
        return final
