"""Verifier agent — Gemini version."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, TestRun, CriterionStatus
from core.board import MessageBoard
from core.logger import RunLogger
from core.gemini_client import make_client, get_model_name, run_agent_loop
from tools.command_tool import run_command
from tools.file_tools import read_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SYSTEM_PROMPT = """You are the Verifier agent in DevPilot.

Steps:
1. Run the project's test suite with run_command (pytest or python3 -m pytest).
2. For each criterion, write a check script via write_check and run it.
3. Edge cases: empty input, large discount (negative total risk), zero values.
4. If pytest is unavailable (exit 127), fall back to python3 -m unittest or python3 -m py_compile.
   Mark the report as "reduced coverage" in that case.
5. Use post_finding for any failure — even if pytest passes but a criterion is not met.
"""

TOOLS = [
    {
        "name": "run_command",
        "description": "Run an allowed command: pytest, python3, ls, cat.",
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
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_check",
        "description": "Write a temporary check script (stored in system temp, NOT in workspace).",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "post_finding",
        "description": "Post a TEST_FAILURE or VERIFY_FINDING message.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["TEST_FAILURE", "VERIFY_FINDING"]},
                "criterion_id": {"type": "string"},
                "description": {"type": "string"},
                "evidence": {"type": "string"},
                "file": {"type": "string"},
                "line": {"type": "integer"},
            },
            "required": ["type", "description", "evidence"],
        },
    },
]


class VerifierAgent:
    """Runs tests and independent criterion checks (Gemini)."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = make_client()
        self.model = get_model_name()
        self.agent_name = "verifier"
        self._temp_dir = tempfile.mkdtemp(prefix="devpilot_verify_")
        self._findings_posted: list[dict] = []
        self._reduced_coverage = False

    def _build_user_message(self) -> str:
        parts = [
            f"## Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
            f"## Temp dir for check scripts\n{self._temp_dir}\n",
            "## Criteria to verify\n",
        ]
        for c in self.state.criteria:
            parts.append(f"- {c.id}: {c.text} [status: {c.status}]")
        if self.state.simulate_missing:
            parts.append(f"\nNOTE: `{self.state.simulate_missing}` is NOT available. Use fallback.")
        parts.append("\nStep 1: Run pytest. Step 2: Write and run check scripts for each criterion.")
        return "\n".join(parts)

    def _dispatch(self, tool_name: str, tool_input: dict) -> str:
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
            if result["exit_code"] == 127:
                self._reduced_coverage = True
                self.board.post("TOOL_UNAVAILABLE", self.agent_name, "orchestrator",
                                {"command": cmd, "error": output})
                self.logger.log(self.agent_name, "TOOL_UNAVAILABLE", tool="run_command",
                                input_summary=cmd, output_summary="command not found")
            tr = TestRun(command=cmd, exit_code=result["exit_code"],
                         output=output[:2000], timestamp=_now())
            self.state.test_runs.append(tr)
            self.logger.log(self.agent_name, "TOOL_CALL", tool="run_command",
                            input_summary=cmd, output_summary=output[:150])
            return f"exit_code={result['exit_code']}\n{output}"

        elif tool_name == "read_file":
            try:
                return read_file(str(Path(ws) / tool_input["path"]), ws)
            except Exception as exc:
                return f"ERROR: {exc}"

        elif tool_name == "write_check":
            fname = Path(tool_input["filename"]).name
            check_path = Path(self._temp_dir) / fname
            check_path.write_text(tool_input["content"], encoding="utf-8")
            self.logger.log(self.agent_name, "TOOL_CALL", tool="write_check",
                            input_summary=fname, output_summary="written")
            return f"Check script written: {check_path}"

        elif tool_name == "post_finding":
            msg_type = tool_input["type"]
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
            cid = tool_input.get("criterion_id", "")
            for c in self.state.criteria:
                if c.id == cid:
                    c.status = CriterionStatus.FAILED
                    c.evidence = tool_input["evidence"][:200]
            self.logger.log(self.agent_name, msg_type,
                            input_summary=tool_input["description"][:80],
                            output_summary=tool_input["evidence"][:80])
            return f"Posted {msg_type}"

        return f"ERROR: unknown tool {tool_name}"

    def run(self) -> dict:
        """Run the verifier."""
        self.logger.log(self.agent_name, "AGENT_START",
                        input_summary=f"{len(self.state.criteria)} criteria")
        steps = self.state.steps_per_agent.get(self.agent_name, 0)
        max_iter = min(15, self.state.max_steps_per_agent - steps)

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
        self.state.last_verify_time = _now()
        summary = {
            "test_runs": len(self.state.test_runs),
            "findings_posted": len(self._findings_posted),
            "reduced_coverage": self._reduced_coverage,
        }
        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=json.dumps(summary))
        return summary
