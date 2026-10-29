"""Planner agent — Gemini version."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, Criterion, Task, CriterionStatus, TaskStatus
from core.board import MessageBoard
from core.logger import RunLogger
from core.gemini_client import make_client, get_model_name, run_agent_loop
from tools.file_tools import read_file, search_code, list_files
from tools.safety import SafetyError


SYSTEM_PROMPT = """You are the Planner agent in DevPilot.

Your job is to turn a user request into clear, testable acceptance criteria and tasks.

Rules:
1. If the request is too vague (e.g. "add a discount" with no specifics), use the clarify tool.
2. Each criterion must be concrete and testable.
3. Tasks must be actionable with owner="developer".
4. When revising after a PLAN_GAP, update existing tasks and add new ones.
5. Read AGENTS.md in the repo before creating criteria.
6. Always call set_plan at the end to finalise the plan.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the workspace or original repo.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"file_glob": {"type": "string", "description": "Glob pattern, default *"}},
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
        "name": "clarify",
        "description": "Ask the human a clarifying question when the request is too vague.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "set_plan",
        "description": "Set the final criteria and tasks for this run.",
        "parameters": {
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
    """Converts the user request into acceptance criteria and tasks (Gemini)."""

    def __init__(self, state: SharedState, board: MessageBoard, logger: RunLogger):
        """Initialize with shared state, message board, and logger."""
        self.state = state
        self.board = board
        self.logger = logger
        self.client = make_client()
        self.model = get_model_name()
        self.agent_name = "planner"
        self._clarify_question: str | None = None
        self._plan_set = False

    @property
    def clarify_question(self) -> str | None:
        return self._clarify_question

    def _build_user_message(self, revision_context: str = "") -> str:
        parts = [
            f"## User Request\n{self.state.request}\n",
            f"## Workspace\n{self.state.workspace_path}\n",
        ]
        if revision_context:
            parts.append(f"\n## PLAN_GAP (must be addressed)\n{revision_context}")
            parts.append("\nYou must issue PLAN_REVISED with updated tasks and criteria.")
        parts.append(
            "\nRead AGENTS.md if it exists, then list_files to understand the repo, "
            "then call set_plan with concrete criteria and tasks. "
            "If the request is too vague, call clarify first."
        )
        return "\n".join(parts)

    def _dispatch(self, tool_name: str, tool_input: dict) -> str:
        ws = self.state.workspace_path
        orig = self.state.repo_path
        try:
            if tool_name == "read_file":
                for try_path, base in [
                    (str(Path(ws) / tool_input["path"]), ws),
                    (str(Path(orig) / tool_input["path"]), orig),
                ]:
                    try:
                        content = read_file(try_path, base)
                        self.logger.log(self.agent_name, "TOOL_CALL", tool="read_file",
                                        input_summary=tool_input["path"])
                        return content
                    except (FileNotFoundError, IsADirectoryError, SafetyError):
                        continue
                return f"ERROR: file not found: {tool_input['path']}"

            elif tool_name == "list_files":
                glob = tool_input.get("file_glob", "*")
                files = list_files(ws, glob)
                self.logger.log(self.agent_name, "TOOL_CALL", tool="list_files")
                return "\n".join(files)

            elif tool_name == "search_code":
                results = search_code(
                    tool_input["pattern"], ws, tool_input.get("file_glob", "*.py")
                )
                return json.dumps(results[:10])

            elif tool_name == "clarify":
                question = tool_input["question"]
                self._clarify_question = question
                self.board.post("CLARIFY", self.agent_name, "human", {"question": question})
                self.logger.log(self.agent_name, "CLARIFY", input_summary=question)
                print(f"\n🤔 CLARIFY: {question}")
                try:
                    answer = input("Your answer (or press Enter to skip): ").strip()
                except EOFError:
                    answer = ""
                return f"Human answered: {answer}" if answer else "No answer provided."

            elif tool_name == "set_plan":
                criteria_raw = tool_input.get("criteria", [])
                tasks_raw = tool_input.get("tasks", [])

                new_criteria = [
                    Criterion(id=c.get("id", f"c{i+1}"), text=c["text"])
                    for i, c in enumerate(criteria_raw)
                ]
                new_tasks = [
                    Task(id=t.get("id", f"t{i+1}"), text=t["text"], owner=t.get("owner", "developer"))
                    for i, t in enumerate(tasks_raw)
                ]

                existing_ids = {c.id for c in self.state.criteria}
                for c in new_criteria:
                    if c.id not in existing_ids:
                        self.state.criteria.append(c)

                existing_task_ids = {t.id for t in self.state.tasks}
                for t in new_tasks:
                    if t.id not in existing_task_ids:
                        self.state.tasks.append(t)

                self._plan_set = True
                msg_type = "PLAN_REVISED" if existing_ids else "PLAN_READY"
                payload = {
                    "criteria": [{"id": c.id, "text": c.text} for c in self.state.criteria],
                    "tasks": [{"id": t.id, "text": t.text} for t in self.state.tasks],
                }
                for receiver in ("developer", "verifier", "reviewer"):
                    self.board.post(msg_type, self.agent_name, receiver, payload)
                self.logger.log(self.agent_name, msg_type,
                                output_summary=f"{len(self.state.criteria)} criteria, {len(self.state.tasks)} tasks")
                return f"Plan set: {len(self.state.criteria)} criteria, {len(self.state.tasks)} tasks"

        except SafetyError as exc:
            return f"BLOCKED: {exc}"
        except Exception as exc:
            return f"ERROR: {exc}"
        return "ERROR: unknown tool"

    def run(self, revision_context: str = "") -> bool:
        """Run the planner. Returns True if a plan was set."""
        self.logger.log(self.agent_name, "AGENT_START", input_summary=self.state.request[:100])
        steps = self.state.steps_per_agent.get(self.agent_name, 0)
        max_iter = min(10, self.state.max_steps_per_agent - steps)

        run_agent_loop(
            client=self.client,
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            tools_config=TOOLS,
            initial_message=self._build_user_message(revision_context),
            dispatch_fn=self._dispatch,
            max_iterations=max_iter,
        )
        self.state.steps_per_agent[self.agent_name] = steps + max_iter
        self.logger.log(self.agent_name, "AGENT_COMPLETE",
                        output_summary=f"plan_set={self._plan_set}, clarify={bool(self._clarify_question)}")
        return self._plan_set
