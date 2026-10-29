"""Per-agent tool permission matrix (ARCHITECTURE.md §F.2). Enforced outside the model; every `—` is tested."""
from __future__ import annotations

# tool -> agents allowed (restrictions beyond this are enforced inside the tool handlers/policies)
ALLOWED: dict[str, set[str]] = {
    "fs.read": {"planner", "developer", "tester", "security", "verifier"},
    "fs.list": {"planner", "developer", "tester", "security", "verifier"},
    "fs.search": {"planner", "developer", "tester", "security", "verifier"},
    "fs.edit": {"developer", "tester"},
    "fs.create": {"developer", "tester"},
    "fs.delete": {"developer"},
    "shell.run": {"planner", "developer", "tester", "verifier"},
    "git.status": {"master", "planner", "developer", "tester", "security", "verifier"},
    "git.diff": {"master", "planner", "developer", "tester", "security", "verifier"},
    "git.checkpoint": {"developer"},
    "git.rollback": {"developer"},
    "check.test": {"developer", "tester", "verifier"},
    "check.lint": {"developer", "tester", "verifier"},
    "check.build": {"developer", "tester", "verifier"},
    "sec.scan_secrets": {"developer", "security", "verifier", "system"},
    "sec.scan_patterns": {"security", "verifier", "system"},
    "sec.audit_deps": {"security", "verifier"},
    "mission.get_state": {"master", "planner", "developer", "tester", "security"},
    "mission.post_message": {"master", "planner", "developer", "tester", "security"},
    "mission.record_finding": {"master", "planner", "tester", "security"},
    "mission.update_task": {"master", "developer", "tester", "security"},
}

SHELL_PROFILE = {"planner": "discovery", "developer": "dev", "tester": "test", "verifier": "verify"}


def is_allowed(agent: str, tool: str) -> bool:
    return agent in ALLOWED.get(tool, set()) or agent == "system"
