"""Independent verifier (AGENTS.md §B.6). Runs as its own OS process: `python -m app.verifier <spec.json> <report.json>`.

ISOLATION CONTRACT (tested in tests/integration/test_verifier.py):
- Inputs: the spec file only (frozen criteria, base commit, candidate patch, workspace git dir to clone from).
- It never opens the database, never reads agent messages, never reuses the developer's working tree or results.
- It clones the BASE commit fresh, applies the PATCH itself, re-derives the test command, and runs everything again.
- Allowed imports: sandbox + common (pure helpers). Not: agents, graph, db, deps, state.manager.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from ..common.detect import detect, purge_pycache
from ..common.parsers import enrich_suspects, parse_junit, parse_unittest
from ..common.tamper import analyze_patch
from ..sandbox.git import GitError, git
from ..sandbox.policy import check_command
from ..sandbox.runner import LocalJailRunner


async def _run_tests(runner: LocalJailRunner, repo: Path, scratch: Path, tag: str, selectors: list[str] | None = None,
                     timeout: int = 180) -> dict[str, Any]:
    purge_pycache(repo)
    cmds = detect(repo)["detected_commands"]
    cands = [c for c in [cmds["test"], *cmds["alternatives"]] if c]
    if not cands:
        return {"outcome": "NO_TESTS", "total": 0, "failed": 0, "errored": 0, "failures": [], "runner": None}
    tried = []
    for c in cands:
        argv = list(c["argv"])
        xml = scratch / f"junit-{tag}.xml"
        if c["runner"] == "pytest":
            argv += ["-p", "no:cacheprovider", f"--junitxml={xml}", *(selectors or [])]
        res = await runner.run(argv, repo, timeout)
        blob = res.stdout + res.stderr
        if res.not_found or "No module named pytest" in blob:
            tried.append(c["runner"])
            continue
        if res.timed_out:
            return {"outcome": "ERROR", "total": 0, "failed": 0, "errored": 1, "runner": c["runner"], "command": " ".join(argv[:3]),
                    "failures": [{"test_id": "<run>", "class": "TIMEOUT", "message": "timed out"}], "output": blob[-600:]}
        if c["runner"] == "pytest" and xml.exists():
            p = parse_junit(xml.read_text("utf-8"))
        elif c["runner"] == "pytest" and res.exit_code == 5:
            return {"outcome": "NO_TESTS", "total": 0, "failed": 0, "errored": 0, "failures": [], "runner": "pytest", "command": " ".join(argv[:3]), "exit_code": 5, "output": blob[-300:]}
        elif c["runner"] == "unittest":
            p = parse_unittest(blob)
        else:
            return {"outcome": "ERROR" if res.exit_code else "GREEN", "total": 0, "failed": 0, "errored": 0, "runner": c["runner"],
                    "failures": [], "output": blob[-600:], "exit_code": res.exit_code}
        enrich_suspects(repo, p.get("failures", []))
        bad = p["failed"] + p["errored"]
        outcome = "GREEN" if bad == 0 and p["total"] > 0 else ("NO_TESTS" if p["total"] == 0 else "RED")
        return {**p, "outcome": outcome, "runner": c["runner"], "command": " ".join(argv[:3]), "exit_code": res.exit_code, "output": blob[-600:]}
    return {"outcome": "UNAVAILABLE", "total": 0, "failed": 0, "errored": 0, "failures": [], "runner": None, "tried": tried}


async def _verify(spec: dict[str, Any]) -> dict[str, Any]:
    t0 = time.monotonic()
    scratch = Path(spec["scratch"])
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    runner = LocalJailRunner(scratch / "home")
    patch_text = Path(spec["patch_file"]).read_text("utf-8") if spec.get("patch_file") else ""
    report: dict[str, Any] = {"patch_sha256": spec["patch_sha256"], "criteria_version": spec["criteria_version"], "results": [],
                              "regression_check": {}, "tamper_check": {}, "overall": "INCONCLUSIVE", "error": None,
                              "isolation": {"fresh_clone_of": spec["base_commit"], "pid_isolated": True}}
    try:
        base_dir, patched_dir = scratch / "base", scratch / "patched"
        for d in (base_dir, patched_dir):
            await git(scratch, "clone", "-q", "--no-hardlinks", spec["workspace_git_dir"], str(d))
            await git(d, "checkout", "-q", spec["base_commit"])
            await git(d, "config", "user.email", "verifier@localhost")
            await git(d, "config", "user.name", "verifier")
        if patch_text.strip():
            pf = scratch / "candidate.patch"
            pf.write_text(patch_text)
            try:
                await git(patched_dir, "apply", "--whitespace=nowarn", str(pf))
            except GitError as e:
                report["error"] = f"candidate patch does not apply to the base commit: {e}"
                report["overall"] = "FAIL"
                return report
        report["tamper_check"] = {k: v for k, v in analyze_patch(patch_text).items() if k != "files"}
        base_run = await _run_tests(runner, base_dir, scratch, "base")
        full_run = await _run_tests(runner, patched_dir, scratch, "patched")
        base_fail = {f["test_id"] for f in base_run.get("failures", [])}
        now_fail = {f["test_id"] for f in full_run.get("failures", [])}
        report["regression_check"] = {
            "baseline_outcome": base_run["outcome"], "patched_outcome": full_run["outcome"], "baseline_failures": sorted(base_fail),
            "new_failures": sorted(now_fail - base_fail), "fixed": sorted(base_fail - now_fail), "command": full_run.get("command"),
            "patched_summary": {k: full_run.get(k) for k in ("total", "failed", "errored", "skipped")},
        }
        for c in spec["criteria"]:
            report["results"].append(await _check_criterion(c, runner, patched_dir, scratch, full_run))
        any_fail = any(r["status"] == "FAIL" for r in report["results"])
        new_regressions = bool(report["regression_check"]["new_failures"])
        if new_regressions:
            report["error"] = None
        if any_fail or new_regressions:
            report["overall"] = "FAIL"
        elif any(r["status"] == "INCONCLUSIVE" for r in report["results"]):
            report["overall"] = "INCONCLUSIVE"
        else:
            report["overall"] = "PASS"
    except Exception as e:  # noqa: BLE001 - a verifier crash must read as INCONCLUSIVE, never PASS
        report["error"] = f"{type(e).__name__}: {e}"[:300]
        report["overall"] = "INCONCLUSIVE"
    report["duration_s"] = round(time.monotonic() - t0, 2)
    return report


async def _check_criterion(c: dict[str, Any], runner: LocalJailRunner, repo: Path, scratch: Path, full_run: dict[str, Any]) -> dict[str, Any]:
    v = c["verification"]
    base = {"ac_id": c["id"], "method": v["method"], "evidence": {}, "confidence": 1.0}
    m = v["method"]
    if m == "command":
        dec = check_command(v.get("argv") or [], "verify", repo)
        if not dec.allowed or dec.argv is None:
            return {**base, "status": "INCONCLUSIVE", "evidence": {"reason": f"command rejected by sandbox policy: {dec.reason}", "argv": v.get("argv")}}
        res = await runner.run(dec.argv, repo, 180)
        ok = res.exit_code == v.get("expect_exit", 0) and not res.timed_out
        return {**base, "status": "PASS" if ok else "FAIL", "evidence": {"command": " ".join(dec.argv), "exit_code": res.exit_code,
                                                                        "expected_exit": v.get("expect_exit", 0), "output_excerpt": (res.stdout + res.stderr)[-500:]}}
    if m == "test_selector":
        sels = v.get("selectors") or []
        for s in sels:
            p = s.split("::", 1)[0]
            if not (repo / p).exists():
                return {**base, "status": "FAIL", "evidence": {"selectors": sels, "reason": f"{p} does not exist in the patched repository"}}
        r = await _run_tests(runner, repo, scratch, f"sel-{c['id']}", sels)
        ok = r["outcome"] == "GREEN" and r.get("total", 0) > 0
        return {**base, "status": "PASS" if ok else "FAIL", "evidence": {"selectors": sels, "outcome": r["outcome"], "total": r.get("total"),
                                                                       "failures": [f["test_id"] for f in r.get("failures", [])][:5], "command": r.get("command"),
                                                                       "output_excerpt": r.get("output", "")[-300:]}}
    if m == "static_check":
        f = repo / (v.get("path") or "")
        if not f.is_file():
            return {**base, "status": "FAIL", "evidence": {"reason": f"{v.get('path')} not found"}}
        text = f.read_text("utf-8", "replace")
        must, must_not = v.get("must_match"), v.get("must_not_match")
        ok = (not must or re.search(must, text, re.M) is not None) and (not must_not or re.search(must_not, text, re.M) is None)
        return {**base, "status": "PASS" if ok else "FAIL", "evidence": {"path": v.get("path"), "must_match": must, "must_not_match": must_not}}
    return {**base, "status": "INCONCLUSIVE", "confidence": 0.0,
            "evidence": {"reason": "manual_review criteria cannot be machine-verified; a human must acknowledge them", "rubric": v.get("rubric")}}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print("usage: python -m app.verifier <spec.json> <report.json>", file=sys.stderr)
        return 2
    spec = json.loads(Path(args[0]).read_text())
    report = asyncio.run(_verify(spec))
    Path(args[1]).write_text(json.dumps(report, indent=1))
    return 0
