"""Reviewer agent: reviews diff, scans for secrets, posts REVIEW_ISSUE messages."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, ReviewIssue
from core.board import MessageBoard
from core.logger import RunLogger
from tools.git_tools import git_diff
from tools.file_tools import read_file, search_code
from tools.secret_scan import scan_directory
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Reviewer agent in DevPilot.

Your job is to review the code changes and ensure quality, security, and correctness.

Steps:
1. Get the git diff between original and workspace.
2. Read each changed file AND the files it imports.
3. Run scan_secrets to check for hardcoded secrets.
4. Check: correctness, readability, consistency with AGENTS.md, security risks.
5. Post REVIEW_ISSUE messages for every problem found (with file, line, evidence).
6. If the Developer replies with DEV_REPLY, check their evidence and either accept or hold firm.

Security checks you MUST make:
- Hardcoded API keys, passwords, tokens (follow import chains!)
- eval() or exec() usage
- String-built SQL queries
- Paths not validated
- Shell injection risks

Style checks:
- Missing docstrings
- Functions too large (>30 lines)
- Inconsistency with AGENTS.md rules

Be thorough. The Reviewer is the quality gate before human approval.
"""

TOOLS = [
    {
        "name": "git_diff",
        "description": "Get the unified diff between original repo and workspace.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_file",
        "description": "Read a file from the workspace (follow import chains).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "scan_secrets",
        "description": "Scan workspace or a specific file for hardcoded secrets and unsafe code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory to scan"},
            },
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern across workspace files.",
        "input_schema": {
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
        "description": "Post a REVIEW_ISSUE message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "file": {"type": "string"},
                "line": {"type": "integer"},
                "text": {"type": "string", "description": "Description of the issue"},
                "evidence": {"type": "string"},
            },
            "required": ["severity", "file", "line", "text", "evidence"],
        },
    },
]


class ReviewerAgent:
    """Reviews code changes and posts issues for the Developer to address."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("MODEL", "claude-opus-4-5")
        self.agent_name = "reviewer"

    def _build_user_message(self) -> str:
        """Build the review task message."""
        # Check for any DEV_REPLY messages
        dev_replies = self.board.get_by_type("DEV_REPLY")
        parts = [
            f"## Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
            f"## Original Repo\n{self.state.repo_path}\n",
            "## Your Task\n",
            "1. Run git_diff to see what changed.\n",
            "2. Read changed files and their imports.\n",
            "3. Run scan_secrets on the workspace.\n",
            "4. Post REVIEW_ISSUE for each problem.\n",
        ]
        if dev_replies:
            parts.append("\n## DEV_REPLY messages to evaluate:\n")
            for m in dev_replies:
                parts.append(f"- {m.payload}")

        if self.state.review_issues:
            parts.append("\n## Previously posted issues:\n")
            for issue in self.state.review_issues:
                parts.append(f"- [{issue.status}] {issue.severity}: {issue.text}")

        return "\n".join(parts)

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call."""
        ws = self.state.workspace_path
        orig = self.state.repo_path

        try:
            if tool_name == "git_diff":
                diff = git_diff(orig, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="git_diff",
                                output_summary=diff[:100])
                return diff or "(no differences)"

            elif tool_name == "read_file":
                path = str(Path(ws) / tool_input["path"])
                content = read_file(path, ws)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                input_summary=tool_input["path"])
                return content

            elif tool_name == "scan_secrets":
                scan_path = tool_input.get("path", ws)
                # Make sure path is under workspace
                if not str(Path(scan_path).resolve()).startswith(str(Path(ws).resolve())):
                    scan_path = ws
                findings = scan_directory(scan_path)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="scan_secrets",
                                output_summary=f"{len(findings)} findings")
                return json.dumps(findings)

            elif tool_name == "search_code":
                glob = tool_input.get("file_glob", "*.py")
                results = search_code(tool_input["pattern"], ws, glob)
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
                                input_summary=f"{tool_input['severity']}: {tool_input['text'][:80]}",
                                output_summary=tool_input.get("evidence", "")[:80])
                return f"Posted issue {issue_id}: {tool_input['text'][:80]}"

        except SafetyError as exc:
            return f"BLOCKED: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"

        return "ERROR: unknown tool"

    def run(self) -> dict:
        """Run the reviewer agent. Returns summary."""
        self.logger.log(self.agent_name, "AGENT_START",
                        input_summary=f"reviewing workspace {self.state.workspace_path}")

        if self.agent_name not in self.state.steps_per_agent:
            self.state.steps_per_agent[self.agent_name] = 0

        messages = [{"role": "user", "content": self._build_user_message()}]
        max_iterations = min(
            12,
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

        summary = {
            "issues_found": len(self.state.review_issues),
            "open_issues": sum(1 for i in self.state.review_issues if i.status == "open"),
            "summary": final_text[:300],
        }
        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=json.dumps(summary)[:200])
        return summary
