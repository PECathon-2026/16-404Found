"""Verifier agent: runs tests and independent criterion checks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, TestRun, CriterionStatus
from core.board import MessageBoard
from core.logger import RunLogger
from tools.command_tool import run_command
from tools.file_tools import read_file, edit_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEM_PROMPT = """You are the Verifier agent in DevPilot.

Your job is TWO steps:
1. Run the project's test suite and record results.
2. For each acceptance criterion, write an independent check script and run it.

Rules:
- Check scripts go in a temp directory, NOT in the workspace or original repo.
- Edge cases you must try: empty cart, large discount (negative total risk), zero price.
- If the test command is unavailable, fall back to: python3 -m unittest or python3 -m py_compile.
  Mark the report as "reduced coverage" in that case.
- If a criterion is not met, post a VERIFY_FINDING message even if pytest passed.
- Be thorough. The Verifier is the last defence before human review.
- Report your findings clearly with evidence (command output, line numbers).
"""

TOOLS = [
    {
        "name": "run_command",
        "description": "Run an allowed command (pytest, python3, ls, cat, git diff).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "description": "Working directory"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_check",
        "description": "Write a temporary check script (stored in system temp, not workspace).",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Script filename (no path)"},
                "content": {"type": "string", "description": "Python script content"},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "post_finding",
        "description": "Post a VERIFY_FINDING or TEST_FAILURE message to the board.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["TEST_FAILURE", "VERIFY_FINDING"],
                },
                "criterion_id": {"type": "string"},
                "description": {"type": "string"},
                "evidence": {"type": "string"},
                "file": {"type": "string", "default": ""},
                "line": {"type": "integer", "default": 0},
            },
            "required": ["type", "description", "evidence"],
        },
    },
]


class VerifierAgent:
    """Runs the project's tests and independent criterion checks."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("MODEL", "claude-opus-4-5")
        self.agent_name = "verifier"
        self._temp_dir = tempfile.mkdtemp(prefix="devpilot_verify_")
        self._findings_posted: list[dict] = []
        self._reduced_coverage = False

    def _build_user_message(self) -> str:
        """Build verification task description."""
        parts = [
            f"## Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
            "## Acceptance Criteria to Verify\n",
        ]
        for c in self.state.criteria:
            parts.append(f"- {c.id}: {c.text} [current status: {c.status}]")

        parts.append(f"\n## Temp directory for check scripts\n{self._temp_dir}")
        parts.append("\nStep 1: Run `pytest` in the workspace. If pytest is unavailable, try fallbacks.")
        parts.append("Step 2: For each criterion, write a check script to verify it independently.")
        parts.append("Step 3: Use post_finding tool for any failures you detect.")

        if self.state.simulate_missing:
            parts.append(f"\nNOTE: `{self.state.simulate_missing}` is NOT available. Use fallback tools.")

        return "\n".join(parts)

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return result."""
        ws = self.state.workspace_path

        if tool_name == "run_command":
            cmd = tool_input["command"]
            cwd = tool_input.get("cwd", ws)
            result = run_command(cmd, ws, cwd, self.state.simulate_missing)
            output = result["stdout"] + result["stderr"]

            if result["blocked"]:
                self.logger.log(self.agent_name, "BLOCKED", tool="run_command",
                                input_summary=cmd, output_summary=result["error"])
                return f"BLOCKED: {result['error']}"

            # Check for missing tool (exit 127)
            if result["exit_code"] == 127:
                self._reduced_coverage = True
                self.logger.log(self.agent_name, "TOOL_UNAVAILABLE", tool="run_command",
                                input_summary=cmd, output_summary="command not found")
                self.board.post("TOOL_UNAVAILABLE", self.agent_name, "orchestrator",
                                {"command": cmd, "error": output})

            # Record test run
            test_run = TestRun(
                command=cmd,
                exit_code=result["exit_code"],
                output=output[:2000],
                timestamp=_now(),
            )
            self.state.test_runs.append(test_run)
            self.logger.log(self.agent_name, "TOOL_CALL", tool="run_command",
                            input_summary=cmd, output_summary=output[:200])
            return f"exit_code={result['exit_code']}\n{output}"

        elif tool_name == "read_file":
            try:
                path = str(Path(ws) / tool_input["path"])
                content = read_file(path, ws)
                return content
            except Exception as exc:
                return f"ERROR: {exc}"

        elif tool_name == "write_check":
            filename = Path(tool_input["filename"]).name  # strip any path
            check_path = Path(self._temp_dir) / filename
            check_path.write_text(tool_input["content"], encoding="utf-8")
            self.logger.log(self.agent_name, "TOOL_CALL", tool="write_check",
                            input_summary=filename, output_summary="written")
            return f"Check script written to: {check_path}"

        elif tool_name == "post_finding":
            msg_type = tool_input["type"]  # TEST_FAILURE or VERIFY_FINDING
            payload = {
                "criterion_id": tool_input.get("criterion_id", ""),
                "description": tool_input["description"],
                "evidence": tool_input["evidence"],
                "file": tool_input.get("file", ""),
                "line": tool_input.get("line", 0),
                "reduced_coverage": self._reduced_coverage,
            }
            self.board.post(msg_type, self.agent_name, "developer", payload)
            self.board.post(msg_type, self.agent_name, "orchestrator", payload)
            self._findings_posted.append(payload)

            # Update criterion status
            cid = tool_input.get("criterion_id", "")
            for c in self.state.criteria:
                if c.id == cid:
                    c.status = CriterionStatus.FAILED
                    c.evidence = tool_input["evidence"][:200]

            self.logger.log(self.agent_name, msg_type,
                            input_summary=tool_input["description"],
                            output_summary=tool_input["evidence"][:100])
            return f"Posted {msg_type}: {tool_input['description'][:100]}"

        return f"ERROR: unknown tool {tool_name}"

    def run(self) -> dict:
        """Run the verifier. Returns summary dict."""
        self.logger.log(self.agent_name, "AGENT_START",
                        input_summary=f"verifying {len(self.state.criteria)} criteria")

        if self.agent_name not in self.state.steps_per_agent:
            self.state.steps_per_agent[self.agent_name] = 0

        messages = [{"role": "user", "content": self._build_user_message()}]
        max_iterations = min(
            15,
            self.state.max_steps_per_agent - self.state.steps_per_agent.get(self.agent_name, 0)
        )

        final_text = ""

        for _i in range(max_iterations):
            self.state.steps_per_agent[self.agent_name] = \
                self.state.steps_per_agent.get(self.agent_name, 0) + 1

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            tool_calls = []
            text_parts = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(block)

            final_text = "\n".join(text_parts)

            if not tool_calls:
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for tc in tool_calls:
                res = self._dispatch_tool(tc.name, tc.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": res,
                })
            messages.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                break

        # Update last verify time
        self.state.last_verify_time = _now()

        summary = {
            "test_runs": len(self.state.test_runs),
            "findings_posted": len(self._findings_posted),
            "reduced_coverage": self._reduced_coverage,
            "summary": final_text[:300],
        }
        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=json.dumps(summary)[:200])
        return summary
