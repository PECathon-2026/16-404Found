"""Test-output parsing and failure classification (T4.04). Deterministic: no LLM involved."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any

from ..state.enums import FailureClass

_FRAME = re.compile(r'File "([^"]+)", line (\d+)')
_PYTEST_LOC = re.compile(r"^([\w./-]+\.py):(\d+):", re.M)


def classify(text: str, type_hint: str = "") -> FailureClass:
    blob = f"{type_hint}\n{text}"
    if re.search(r"No module named pytest|command not found|No such file or directory: 'npm'", blob):
        return FailureClass.ENV_MISSING_TOOL
    if re.search(r"ModuleNotFoundError|ImportError|cannot import name", blob):
        return FailureClass.IMPORT_ERROR
    if re.search(r"SyntaxError|IndentationError|TabError", blob):
        return FailureClass.SYNTAX_ERROR
    if re.search(r"TimeoutError|timed out", blob):
        return FailureClass.TIMEOUT
    if re.search(r"AssertionError|assert ", blob):
        return FailureClass.ASSERTION
    if re.search(r"TypeError|AttributeError|NameError|KeyError|IndexError|ValueError|ZeroDivisionError", blob):
        return FailureClass.TYPE_ERROR
    return FailureClass.UNKNOWN


def suspected_files(trace: str, ws_files: set[str] | None = None) -> list[str]:
    found: list[str] = []
    for m in list(_FRAME.finditer(trace)) + list(_PYTEST_LOC.finditer(trace)):
        p = m.group(1)
        norm = p.split("/workspace/")[-1] if "/workspace/" in p else p
        for marker in ("/workspaces/",):
            if marker in p:
                norm = p.split(marker, 1)[1].split("/", 1)[-1]
        if "site-packages" in p or "/lib/python" in p or norm.startswith("/"):
            continue
        if norm not in found:
            found.append(norm)
    non_test = [f for f in found if not re.search(r"(^|/)(test_[^/]+|[^/]+_test)\.py$|(^|/)tests?/", f)]
    return (non_test + [f for f in found if f not in non_test])[:6]


def parse_junit(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = passed = failed = errored = skipped = 0
    dur = 0.0
    failures: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    for s in suites:
        dur += float(s.get("time", 0) or 0)
        for tc in s.iter("testcase"):
            total += 1
            name = f"{(tc.get('classname') or '').replace('.', '/')}.py::{tc.get('name')}" if tc.get("classname") else tc.get("name", "")
            if tc.get("file"):
                name = f"{tc.get('file')}::{tc.get('name')}"
            bad = tc.find("failure")
            err = tc.find("error")
            status = "SKIPPED" if tc.find("skipped") is not None else "FAILED" if (bad is not None or err is not None) else "PASSED"
            if len(cases) < 400:
                cases.append({"test_id": name, "status": status, "duration_s": float(tc.get("time", 0) or 0)})
            if tc.find("skipped") is not None:
                skipped += 1
            elif bad is not None or err is not None:
                el = bad if bad is not None else err
                assert el is not None
                if bad is not None:
                    failed += 1
                else:
                    errored += 1
                trace = (el.text or "")[-2500:]
                msg = (el.get("message") or "")[:400]
                failures.append({
                    "test_id": name, "class": str(classify(trace + msg, el.get("type") or "")), "message": msg,
                    "trace_excerpt": trace, "suspected_files": suspected_files(trace),
                })
            else:
                passed += 1
    return {"total": total, "passed": passed, "failed": failed, "errored": errored, "skipped": skipped,
            "duration_s": round(dur, 3), "failures": failures, "cases": cases}


def parse_unittest(output: str) -> dict[str, Any]:
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    total = int(ran.group(1)) if ran else 0
    failed = errored = 0
    m = re.search(r"FAILED \((.*?)\)", output)
    if m:
        f = re.search(r"failures=(\d+)", m.group(1))
        e = re.search(r"errors=(\d+)", m.group(1))
        failed = int(f.group(1)) if f else 0
        errored = int(e.group(1)) if e else 0
    skipped = 0
    sk = re.search(r"skipped=(\d+)", output)
    if sk:
        skipped = int(sk.group(1))
    failures = []
    for block in re.split(r"\n={20,}\n", output)[1:]:
        head = block.split("\n", 1)[0]
        hm = re.match(r"(FAIL|ERROR): (\w+) \(([\w.]+)\)", head)
        if not hm:
            continue
        trace = block[-2500:]
        failures.append({
            "test_id": f"{hm.group(3).replace('.', '/')}::{hm.group(2)}", "class": str(classify(trace)),
            "message": (trace.strip().splitlines() or [""])[-1][:400], "trace_excerpt": trace,
            "suspected_files": suspected_files(trace),
        })
    return {"total": total, "passed": max(total - failed - errored - skipped, 0), "failed": failed, "errored": errored,
            "skipped": skipped, "duration_s": float(ran.group(2)) if ran else 0.0, "failures": failures}


def fingerprint(failures: list[dict[str, Any]]) -> str:
    """Stable identity of a failure state: sorted test ids + class + suspected non-test file (no line numbers)."""
    parts = sorted(f"{f['test_id']}|{f.get('class')}|{(f.get('suspected_files') or [''])[0]}" for f in failures)
    return "sha1:" + hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]


_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def enrich_suspects(ws, failures: list[dict[str, Any]]) -> None:
    """An assertion that fails inside a test blames the test file; point at what the test imports instead."""
    from pathlib import Path

    ws = Path(ws)
    index: dict[str, str] | None = None
    for f in failures:
        tid = f.get("test_id", "")
        tpath = tid.split("::", 1)[0]
        tf = ws / tpath
        if not tpath.endswith(".py") or not tf.is_file():
            continue
        if index is None:
            index = {}
            for p in ws.rglob("*.py"):
                rel = p.relative_to(ws)
                if any(x in {".git", "node_modules", "__pycache__", ".venv"} for x in rel.parts):
                    continue
                index[str(rel.with_suffix("")).replace("/", ".")] = str(rel)
        mods = {m.group(1) or m.group(2) for m in _IMPORT.finditer(tf.read_text("utf-8", "replace"))}
        found: list[str] = []
        for mod in sorted(mods):
            for key, rel in index.items():
                if (key == mod or key.endswith("." + mod) or mod.endswith("." + key) or mod.startswith(key + ".")) and rel != tpath:
                    if not re.search(r"(^|/)(test_[^/]+|[^/]+_test|conftest)\.py$|(^|/)tests?/", rel) and rel not in found:
                        found.append(rel)
        cur = list(f.get("suspected_files") or [])
        impl = [x for x in cur if x in found or not re.search(r"(^|/)(test_[^/]+|[^/]+_test)\.py$|(^|/)tests?/", x)]
        f["suspected_files"] = (impl + [x for x in found if x not in impl] + [x for x in cur if x not in impl])[:6]
