"""Single-agent baseline: one Anthropic tool-use loop for comparison with DevPilot."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

from tools.file_tools import read_file, edit_file, search_code, list_files
from tools.command_tool import run_command
from tools.git_tools import git_diff


SYSTEM_PROMPT = """You are a skilled developer. Your job is to implement the requested code change.
Read the existing files first. Make the change. Run tests to verify. Report your result.
Use Decimal for money math. Follow the repo's AGENTS.md if present.
"""

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Write content to a file.",
        "input_schema": {
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
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "list_files",
        "description": "List files.",
        "input_schema": {
            "type": "object",
            "properties": {"file_glob": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "search_code",
        "description": "Search code.",
        "input_schema": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "file_glob": {"type": "string"}},
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
    """
    Run the single-agent baseline on a copy of repo_path.

    Returns result dict with: success, steps, test_output, final_message, run_id.
    """
    run_id = f"baseline_{uuid.uuid4().hex[:8]}"
    ws_path = Path(tempfile.mkdtemp(prefix=f"devpilot_baseline_{run_id}_"))
    shutil.copytree(str(repo_path), str(ws_path), dirs_exist_ok=True)

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    model = os.getenv("MODEL", "claude-opus-4-5")

    user_msg = (
        f"Request: {request}\n"
        f"Workspace: {ws_path}\n"
        "Implement the request, run tests, and report your result."
    )

    messages = [{"role": "user", "content": user_msg}]
    steps = 0
    test_outputs = []
    final_message = ""
    bugs_caught = 0
    secrets_caught = 0

    def dispatch(tool_name: str, tool_input: dict) -> str:
        nonlocal bugs_caught, secrets_caught
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
            return json.dumps(search_code(tool_input["pattern"], ws, tool_input.get("file_glob", "*.py"))[:10])
        return "unknown tool"

    for _ in range(max_steps):
        steps += 1
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        text_parts = [b.text for b in response.content if b.type == "text"]
        if text_parts:
            final_message = "\n".join(text_parts)

        if not tool_calls:
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tc in tool_calls:
            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": dispatch(tc.name, tc.input),
            })
        messages.append({"role": "user", "content": results})

        if response.stop_reason == "end_turn":
            break

    # Determine success from last test output
    success = any("passed" in o.lower() and "failed" not in o.lower() for o in test_outputs)

    result = {
        "run_id": run_id,
        "request": request,
        "success": success,
        "steps": steps,
        "test_output": test_outputs[-1] if test_outputs else "",
        "final_message": final_message[:500],
        "bugs_caught": bugs_caught,
        "secrets_caught": secrets_caught,
        "workspace": str(ws_path),
    }

    # Save result
    from pathlib import Path as P
    runs_dir = P(__file__).parent.parent / "runs"
    runs_dir.mkdir(exist_ok=True)
    result_path = runs_dir / f"{run_id}_result.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Baseline result: {result_path}")
    return result


if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "demo_repos/mini_shop"
    req = sys.argv[2] if len(sys.argv) > 2 else (
        "Add coupon support. SAVE10 gives 10% off. "
        "Apply it via cart.total_with_coupon('SAVE10')."
    )
    result = run_single_agent(repo, req)
    print(json.dumps(result, indent=2))
