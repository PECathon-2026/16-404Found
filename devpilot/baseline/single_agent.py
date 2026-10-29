"""Single-agent baseline using Gemini — for comparison with DevPilot."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.gemini_client import make_client, get_model_name, run_agent_loop
from tools.file_tools import read_file, edit_file, search_code, list_files
from tools.command_tool import run_command
from tools.git_tools import git_diff


SYSTEM_PROMPT = """You are a skilled developer. Implement the requested code change.
Read existing files first. Make the change. Run tests to verify. Report your result.
Use Decimal for money math. Follow the repo's AGENTS.md if present.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Write content to a file.",
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
        "name": "run_command",
        "description": "Run pytest or python3.",
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
        "name": "list_files",
        "description": "List files.",
        "parameters": {
            "type": "object",
            "properties": {"file_glob": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search code.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "file_glob": {"type": "string"},
            },
            "required": ["pattern"],
        },
    },
]


def run_single_agent(
    repo_path: str | Path,
    request: str,
    max_steps: int = 20,
    simulate_missing: str | None = None,
) -> dict:
    """Run the single-agent Gemini baseline on a copy of repo_path."""
    run_id = f"baseline_{uuid.uuid4().hex[:8]}"
    ws_path = Path(tempfile.mkdtemp(prefix=f"devpilot_baseline_{run_id}_"))
    shutil.copytree(str(repo_path), str(ws_path), dirs_exist_ok=True)

    client = make_client()
    model = get_model_name()

    test_outputs: list[str] = []
    bugs_caught = 0

    def dispatch(tool_name: str, tool_input: dict) -> str:
        nonlocal bugs_caught
        ws = str(ws_path)
        if tool_name == "read_file":
            try:
                return read_file(str(ws_path / tool_input["path"]), ws)
            except Exception as exc:
                return f"ERROR: {exc}"
        elif tool_name == "edit_file":
            try:
                edit_file(str(ws_path / tool_input["path"]), tool_input["content"], ws)
                return "written"
            except Exception as exc:
                return f"ERROR: {exc}"
        elif tool_name == "run_command":
            r = run_command(tool_input["command"], ws, tool_input.get("cwd"), simulate_missing)
            out = r["stdout"] + r["stderr"]
            if r["blocked"]:
                return f"BLOCKED: {r['error']}"
            test_outputs.append(out[:500])
            if r["exit_code"] != 0:
                bugs_caught += 1
            return f"exit={r['exit_code']}\n{out}"
        elif tool_name == "list_files":
            return "\n".join(list_files(ws, tool_input.get("file_glob", "*")))
        elif tool_name == "search_code":
            return json.dumps(
                search_code(tool_input["pattern"], ws, tool_input.get("file_glob", "*.py"))[:10]
            )
        return "unknown tool"

    user_msg = (
        f"Request: {request}\n"
        f"Workspace: {ws_path}\n"
        "Implement the request, run tests, and report your result."
    )

    final_message = run_agent_loop(
        client=client,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools_config=TOOLS,
        initial_message=user_msg,
        dispatch_fn=dispatch,
        max_iterations=max_steps,
    )

    success = any(
        "passed" in o.lower() and "failed" not in o.lower() for o in test_outputs
    )

    result = {
        "run_id": run_id,
        "request": request,
        "success": success,
        "steps": max_steps,
        "test_output": test_outputs[-1] if test_outputs else "",
        "final_message": final_message[:500],
        "bugs_caught": bugs_caught,
        "secrets_caught": 0,
        "workspace": str(ws_path),
    }

    runs_dir = Path(__file__).parent.parent / "runs"
    runs_dir.mkdir(exist_ok=True)
    result_path = runs_dir / f"{run_id}_result.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Baseline result: {result_path}")
    return result


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "demo_repos/mini_shop"
    req = sys.argv[2] if len(sys.argv) > 2 else (
        "Add coupon support. SAVE10 gives 10% off. Apply via cart.total_with_coupon('SAVE10')."
    )
    result = run_single_agent(repo, req)
    print(json.dumps(result, indent=2))
