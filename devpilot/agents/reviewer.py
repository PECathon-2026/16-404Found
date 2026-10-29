"""Reviewer agent — Gemini version."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, ReviewIssue
from core.board import MessageBoard
from core.logger import RunLogger
from core.gemini_client import make_client, get_model_name, run_agent_loop
from tools.git_tools import git_diff
from tools.file_tools import read_file, search_code
from tools.secret_scan import scan_directory
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Reviewer agent in DevPilot.

Steps:
1. Call git_diff to see what changed.
2. Read each changed file AND the files it imports.
3. Call scan_secrets on the workspace.
4. Check: correctness, readability, AGENTS.md consistency, security.
5. Call post_issue for every problem with file, line, and evidence.
6. If a DEV_REPLY exists, evaluate it: accept or hold firm.

Security checks you MUST make:
- Hardcoded API keys, passwords (follow import chains!)
- eval() or exec() usage
- String-built SQL queries
- Missing input validation
"""

TOOLS = [
    {
        "name": "git_diff",
        "description": "Get the unified diff between original repo and workspace.",
        "parameters": {"type": "object", "properties": {}, "required": []},
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
        "name": "scan_secrets",
        "description": "Scan workspace for hardcoded secrets and unsafe code.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern in workspace files.",
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
        "name": "post_issue",
        "description": "Post a REVIEW_ISSUE.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "file": {"type": "string"},
                "line": {"type": "integer"},
                "text": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["severity", "file", "line", "text", "evidence"],
        },
    },
]


class ReviewerAgent:
    """Reviews code changes and posts issues (Gemini)."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = make_client()
        self.model = get_model_name()
        self.agent_name = "reviewer"

    def _build_user_message(self) -> str:
        parts = [
            f"## Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
            f"## Original Repo\n{self.state.repo_path}\n",
            "## Task\n1. Run git_diff.\n2. Read changed files and their imports.\n3. Run scan_secrets.\n4. Post issues.\n",
        ]
        dev_replies = self.board.get_by_type("DEV_REPLY")
        if dev_replies:
            parts.append("\n## DEV_REPLY messages to evaluate:\n")
            for m in dev_replies:
                parts.append(f"- {m.payload}")
        return "\n".join(parts)

    def _dispatch(self, tool_name: str, tool_input: dict) -> str:
        ws = self.state.workspace_path
        orig = self.state.repo_path
        try:
            if tool_name == "git_diff":
                diff = git_diff(orig, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="git_diff",
                                output_summary=diff[:80])
                return diff or "(no differences)"

            elif tool_name == "read_file":
                content = read_file(str(Path(ws) / tool_input["path"]), ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                input_summary=tool_input["path"])
                return content

            elif tool_name == "scan_secrets":
                scan_path = tool_input.get("path", ws)
                if not str(Path(scan_path).resolve()).startswith(str(Path(ws).resolve())):
                    scan_path = ws
                findings = scan_directory(scan_path)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="scan_secrets",
                                output_summary=f"{len(findings)} findings")
                return json.dumps(findings)

            elif tool_name == "search_code":
                results = search_code(
                    tool_input["pattern"], ws, tool_input.get("file_glob", "*.py")
                )
                return json.dumps(results[:20])

            elif tool_name == "post_issue":
                issue_id = str(uuid.uuid4())[:8]
                issue = ReviewIssue(
                    id=issue_id,
                    severity=tool_input["severity"],
                    file=tool_input["file"],
                    line=tool_input["line"],
                    text=tool_input["text"],
                    status="open",
                )
                self.state.review_issues.append(issue)
                payload = {
                    "issue_id": issue_id,
                    "severity": tool_input["severity"],
                    "file": tool_input["file"],
                    "line": tool_input["line"],
                    "text": tool_input["text"],
                    "evidence": tool_input.get("evidence", ""),
                }
                self.board.post("REVIEW_ISSUE", self.agent_name, "developer", payload)
                self.board.post("REVIEW_ISSUE", self.agent_name, "orchestrator", payload)
                self.logger.log(self.agent_name, "REVIEW_ISSUE",
                                input_summary=f"{tool_input['severity']}: {tool_input['text'][:60]}",
                                output_summary=tool_input.get("evidence", "")[:60])
                return f"Posted issue {issue_id}"

        except SafetyError as exc:
            return f"BLOCKED: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"
        return "ERROR: unknown tool"

    def run(self) -> dict:
        """Run the reviewer."""
        self.logger.log(self.agent_name, "AGENT_START",
                        input_summary=f"reviewing {self.state.workspace_path}")
        steps = self.state.steps_per_agent.get(self.agent_name, 0)
        max_iter = min(12, self.state.max_steps_per_agent - steps)

        run_agent_loop(
            client=self.client,
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools_config=TOOLS,
            initial_message=self._build_user_message(),
            dispatch_fn=self._dispatch,
            max_iterations=max_iter,
        )
        self.state.steps_per_agent[self.agent_name] = steps + max_iter
        summary = {
            "issues_found": len(self.state.review_issues),
            "open_issues": sum(1 for i in self.state.review_issues if i.status == "open"),
        }
        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=json.dumps(summary))
        return summary
