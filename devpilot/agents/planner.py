"""Planner agent: turns a request into criteria and tasks, handles ambiguity."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, Criterion, Task, CriterionStatus, TaskStatus
from core.board import MessageBoard
from core.logger import RunLogger
from tools.file_tools import read_file, search_code, list_files
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Planner agent in DevPilot.

Your job is to turn a user request into clear, testable acceptance criteria and tasks.

Rules:
1. If the request is too vague (e.g. "add a discount" without specifying code, amount, or behavior),
   use the clarify tool to ask the human ONE specific question.
2. Each criterion must be concrete and testable (not "works well" but "cart.total_with_coupon('X') returns Y").
3. Tasks must be actionable with a clear owner ("developer").
4. When revising the plan after a PLAN_GAP, update existing tasks and add new ones.
5. Read AGENTS.md in the repo before creating criteria.
6. Keep criteria focused on the stated request only.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace or original repo.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"file_glob": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search for a pattern in workspace files.",
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
        "name": "clarify",
        "description": "Ask the human a clarifying question when the request is too vague.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "set_plan",
        "description": "Set the final criteria and tasks for this run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                        },
                    },
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "owner": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["criteria", "tasks"],
        },
    },
]


class PlannerAgent:
    """Converts the user request into acceptance criteria and tasks."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("MODEL", "claude-opus-4-5")
        self.agent_name = "planner"
        self._clarify_question: str | None = None
        self._plan_set = False

    @property
    def clarify_question(self) -> str | None:
        """Return any clarify question posted during this run."""
        return self._clarify_question

    def _build_user_message(self, revision_context: str = "") -> str:
        """Build the planning task message."""
        parts = [
            f"## User Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
        ]

        # Include PLAN_GAP context if revising
        if revision_context:
            parts.append(f"\n## PLAN_GAP (must be addressed)\n{revision_context}")
            parts.append("\nYou must issue PLAN_REVISED with updated tasks and criteria.")

        parts.append(
            "\nRead AGENTS.md if it exists, then list_files to understand the repo structure, "
            "then set_plan with concrete, testable criteria and tasks."
        )
        parts.append(
            "\nIf the request is too vague (no specifics), use clarify to ask ONE question."
        )
        return "\n".join(parts)

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call."""
        ws = self.state.workspace_path
        orig = self.state.repo_path

        try:
            if tool_name == "read_file":
                # Try workspace first, then original repo
                path_ws = str(Path(ws) / tool_input["path"])
                path_orig = str(Path(orig) / tool_input["path"])
                for try_path, base in [(path_ws, ws), (path_orig, orig)]:
                    try:
                        content = read_file(try_path, base)
                        self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                        input_summary=tool_input["path"])
                        return content
                    except (FileNotFoundError, IsADirectoryError):
                        continue
                return f"ERROR: file not found: {tool_input['path']}"

            elif tool_name == "list_files":
                glob = tool_input.get("file_glob", "*")
                files = list_files(ws, glob)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="list_files",
                                output_summary=str(files[:10]))
                return "\n".join(files)

            elif tool_name == "search_code":
                glob = tool_input.get("file_glob", "*.py")
                results = search_code(tool_input["pattern"], ws, glob)
                return json.dumps(results[:10])

            elif tool_name == "clarify":
                question = tool_input["question"]
                self._clarify_question = question
                self.board.post("CLARIFY", self.agent_name, "human", {"question": question})
                self.logger.log(self.agent_name, "CLARIFY", input_summary=question)
                # In CLI mode, ask the human
                print(f"\n🤔 CLARIFY: {question}")
                try:
                    answer = input("Your answer (or press Enter to skip): ").strip()
                except EOFError:
                    answer = ""
                if answer:
                    return f"Human answered: {answer}"
                return "Human did not answer. Proceeding with best-effort interpretation."

            elif tool_name == "set_plan":
                criteria_raw = tool_input.get("criteria", [])
                tasks_raw = tool_input.get("tasks", [])

                # Build Criterion objects
                new_criteria = []
                for c in criteria_raw:
                    cid = c.get("id") or f"c{len(new_criteria)+1}"
                    new_criteria.append(Criterion(id=cid, text=c["text"]))

                # Build Task objects
                new_tasks = []
                for t in tasks_raw:
                    tid = t.get("id") or f"t{len(new_tasks)+1}"
                    new_tasks.append(Task(id=tid, text=t["text"], owner=t.get("owner", "developer")))

                # Merge with existing (for revision)
                existing_ids = {c.id for c in self.state.criteria}
                for c in new_criteria:
                    if c.id not in existing_ids:
                        self.state.criteria.append(c)
                    else:
                        # Update existing
                        for ec in self.state.criteria:
                            if ec.id == c.id:
                                ec.text = c.text

                existing_task_ids = {t.id for t in self.state.tasks}
                for t in new_tasks:
                    if t.id not in existing_task_ids:
                        self.state.tasks.append(t)

                self._plan_set = True

                # Post appropriate message
                msg_type = "PLAN_REVISED" if self.state.criteria else "PLAN_READY"
                payload = {
                    "criteria": [{"id": c.id, "text": c.text} for c in self.state.criteria],
                    "tasks": [{"id": t.id, "text": t.text} for t in self.state.tasks],
                }
                self.board.post(msg_type, self.agent_name, "developer", payload)
                self.board.post(msg_type, self.agent_name, "verifier", payload)
                self.board.post(msg_type, self.agent_name, "reviewer", payload)

                self.logger.log(self.agent_name, msg_type,
                                output_summary=f"{len(self.state.criteria)} criteria, "
                                              f"{len(self.state.tasks)} tasks")
                return (
                    f"Plan set: {len(self.state.criteria)} criteria, "
                    f"{len(self.state.tasks)} tasks"
                )

        except SafetyError as exc:
            return f"BLOCKED: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"

        return "ERROR: unknown tool"

    def run(self, revision_context: str = "") -> bool:
        """
        Run the planner agent.

        Returns True if a plan was set, False if clarification is needed.
        """
        self.logger.log(self.agent_name, "AGENT_START",
                        input_summary=self.state.request[:100])

        if self.agent_name not in self.state.steps_per_agent:
            self.state.steps_per_agent[self.agent_name] = 0

        messages = [{"role": "user", "content": self._build_user_message(revision_context)}]
        max_iterations = min(
            10,
            self.state.max_steps_per_agent - self.state.steps_per_agent.get(self.agent_name, 0)
        )

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

            # If clarify was triggered or plan was set, stop
            if self._clarify_question or self._plan_set:
                break

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

        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=f"plan_set={self._plan_set}, "
                                      f"clarify={bool(self._clarify_question)}")
        return self._plan_set
