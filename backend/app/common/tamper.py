"""Test-tamper detection (X-7) and unified-diff analysis. Pure functions over patch text."""
from __future__ import annotations

import re
from typing import Any

_TEST_PATH = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.[jt]sx?|conftest\.py)$|(^|/)(tests?|__tests__)/")
_SKIP = re.compile(r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|@unittest\.skip|\bit\.skip\(|\btest\.skip\(|xit\(|\.only\(")
_ASSERT = re.compile(r"\bassert\b|self\.assert\w+|\bexpect\(")


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def analyze_patch(patch: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.*) b/(.*)", line)
            path = m.group(2) if m else line
            cur = {"path": path, "change_type": "MODIFY", "additions": 0, "deletions": 0, "removed": [], "added": []}
            files.append(cur)
        elif cur is None:
            continue
        elif line.startswith("new file mode"):
            cur["change_type"] = "ADD"
        elif line.startswith("deleted file mode"):
            cur["change_type"] = "DELETE"
        elif line.startswith("rename from"):
            cur["change_type"] = "RENAME"
        elif line.startswith("+") and not line.startswith("+++"):
            cur["additions"] += 1
            cur["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            cur["deletions"] += 1
            cur["removed"].append(line[1:])
    modified_existing: list[str] = []
    weakened: list[dict[str, Any]] = []
    out = []
    for f in files:
        is_test = is_test_path(f["path"])
        flags: list[str] = []
        if is_test and f["change_type"] != "ADD":
            if f["change_type"] == "DELETE":
                flags.append("DELETED")
            if any(r.strip() for r in f["removed"]):
                flags.append("REMOVED_LINES")
            if any(_SKIP.search(a) for a in f["added"]):
                flags.append("SKIP_ADDED")
            if sum(1 for r in f["removed"] if _ASSERT.search(r)) > sum(1 for a in f["added"] if _ASSERT.search(a)):
                flags.append("ASSERT_REMOVED")
            if flags:
                modified_existing.append(f["path"])
            if {"SKIP_ADDED", "ASSERT_REMOVED", "DELETED"} & set(flags):
                weakened.append({"path": f["path"], "flags": flags})
        elif is_test and f["change_type"] == "ADD" and any(_SKIP.search(a) for a in f["added"]):
            flags.append("SKIP_ADDED")
            weakened.append({"path": f["path"], "flags": flags})
        out.append({"path": f["path"], "change_type": f["change_type"], "additions": f["additions"],
                    "deletions": f["deletions"], "is_test_file": is_test, "tamper_flags": flags})
    return {"files": out, "modified_existing_tests": modified_existing, "weakened_assertions": weakened}
