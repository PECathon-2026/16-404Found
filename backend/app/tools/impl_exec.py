"""shell.run, git.* and check.* tools (T2.08–T2.10)."""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from ..common.detect import detect, purge_pycache
from ..common.ids import new_id, now_iso
from ..common.parsers import classify, enrich_suspects, fingerprint, parse_junit, parse_unittest
from ..common.tamper import analyze_patch
from ..db import test_runs
from ..sandbox.git import GitError, git
from ..sandbox.pathjail import PathViolation, resolve_in
from ..sandbox.policy import check_command
from .base import ToolContext, ToolError, ToolSpec
from .permissions import SHELL_PROFILE
from .ws import compute_patch


# ---------------------------------------------------------------- shell.run
class ShellArgs(BaseModel):
    command: str | list[str]
    cwd: str = "."
    timeout_s: int = Field(60, ge=1, le=300)


async def shell_run(ctx: ToolContext, a: ShellArgs) -> dict:
    profile = SHELL_PROFILE.get(ctx.agent_id, "discovery")
    perms = ctx.config.get("permissions", {})
    dec = check_command(a.command, profile, ctx.workspace, allow_install_deps=bool(perms.get("allow_install_deps")),
                        extra_allowed=tuple(perms.get("extra_allowed_commands", [])))
    if not dec.allowed or dec.argv is None:
        raise ToolError("POLICY_DENIED", dec.reason)
    try:
        cwd = resolve_in(ctx.workspace, a.cwd)
    except PathViolation as e:
        raise ToolError("POLICY_DENIED", str(e)) from None
    res = await ctx.runner.run(dec.argv, cwd, a.timeout_s)
    if res.not_found:
        raise ToolError("ENV_MISSING_TOOL", f"{dec.argv[0]} is not available in the sandbox")
    return {"exit_code": res.exit_code, "stdout": res.stdout[-8000:], "stderr": res.stderr[-4000:], "timed_out": res.timed_out,
            "duration_ms": res.duration_ms, "truncated": res.truncated}


# ---------------------------------------------------------------- git.*
class NoArgs(BaseModel):
    pass


async def git_status(ctx: ToolContext, a: NoArgs) -> dict:
    await git(ctx.workspace, "add", "-A")
    out = await git(ctx.workspace, "status", "--short")
    return {"status": out.strip().splitlines()[:200]}


class DiffArgs(BaseModel):
    paths: list[str] = []


async def git_diff(ctx: ToolContext, a: DiffArgs) -> dict:
    patch, sha = await compute_patch(ctx)
    info = analyze_patch(patch)
    files = [f for f in info["files"] if not a.paths or f["path"] in a.paths]
    return {"patch_sha256": sha, "files": files, "patch": patch[:20000], "truncated": len(patch) > 20000}


class CheckpointArgs(BaseModel):
    message: str = Field("devpilot checkpoint", max_length=200)


async def git_checkpoint(ctx: ToolContext, a: CheckpointArgs) -> dict:
    patch, sha = await compute_patch(ctx)
    try:
        await git(ctx.workspace, "commit", "-q", "-m", a.message)
    except GitError:
        pass  # nothing new to commit
    ref = (await git(ctx.workspace, "rev-parse", "HEAD")).strip()
    cid = ctx.deps.state.checkpoint(ctx.mission_id, "PATCH", "CHECKPOINT", patch_sha=sha, git_ref=ref)
    return {"checkpoint_id": cid, "git_ref": ref, "patch_sha256": sha}


class RollbackArgs(BaseModel):
    checkpoint_id: str


async def git_rollback(ctx: ToolContext, a: RollbackArgs) -> dict:
    from ..db import checkpoints

    row = ctx.deps.db.get(checkpoints, a.checkpoint_id)
    if not row or row["mission_id"] != ctx.mission_id or not row.get("git_ref"):
        raise ToolError("NOT_FOUND", "checkpoint not found for this mission")
    await git(ctx.workspace, "reset", "-q", "--hard", row["git_ref"])
    await git(ctx.workspace, "clean", "-qfd")  # workspace-only: cwd is the mission workspace
    patch, sha = await compute_patch(ctx)
    ctx.deps.state.update_mission(ctx.mission_id, current_patch_sha256=sha)
    return {"rolled_back_to": row["git_ref"], "patch_sha256": sha}


# ---------------------------------------------------------------- check.*
class TestArgs(BaseModel):
    scope: list[str] = []
    timeout_s: int = Field(180, ge=5, le=600)
    kind: Literal["TEST", "BASELINE", "CONFIRM", "SELF_CHECK"] = "TEST"


def _row(ctx: ToolContext, run_id: str, kind: str, runner: str, command: str, sha: str | None, parsed: dict, outcome: str, dur: float) -> dict:
    failures = [{**f, "trace_excerpt": f.get("trace_excerpt", "")[-1500:]} for f in parsed.get("failures", [])[:30]]
    row = dict(id=run_id, mission_id=ctx.mission_id, task_id=ctx.task_id, tool_call_id=ctx.current_tcl, kind=kind, runner=runner,
               command=command, patch_sha256=sha, total=parsed.get("total", 0), passed=parsed.get("passed", 0),
               failed=parsed.get("failed", 0), errored=parsed.get("errored", 0), skipped=parsed.get("skipped", 0),
               duration_s=dur, failures=failures, outcome=outcome, created_at=now_iso())
    ctx.deps.db.insert(test_runs, **row)
    return row


def _env_missing(res, runner: str) -> bool:
    blob = res.stdout + res.stderr
    return bool(res.not_found or f"No module named {runner}" in blob or "command not found" in blob
                or "No module named pytest" in blob)


async def check_test(ctx: ToolContext, a: TestArgs) -> dict:
    d = ctx.deps
    purge_pycache(ctx.workspace)
    for s in a.scope:
        try:
            resolve_in(ctx.workspace, s.split("::", 1)[0])
        except PathViolation as e:
            raise ToolError("POLICY_DENIED", str(e)) from None
    # Only unscoped runs by the tester/system/verifier are gate evidence. A developer's (or any scoped) run is a
    # SELF_CHECK: informative for the developer, never counted by the completion gate or the failure watchdog.
    if a.kind == "TEST" and (ctx.agent_id == "developer" or a.scope):
        a = a.model_copy(update={"kind": "SELF_CHECK"})
    cmds = detect(ctx.workspace)["detected_commands"]
    cands = [c for c in [cmds["test"], *cmds["alternatives"]] if c]
    run_id = new_id("tst")
    sha = None if a.kind == "BASELINE" else (await compute_patch(ctx))[1]
    disabled = set(ctx.config.get("permissions", {}).get("disabled_tools", []))
    if not cands:
        row = _row(ctx, run_id, a.kind, "none", "", sha, {}, "NO_TESTS", 0.0)
        d.bus.publish(ctx.mission_id, "test.passed", ctx.agent_id, {"test_run_id": run_id, "kind": a.kind, "command": "", "patch_sha256": sha,
                      "summary": {"total": 0}, "note": "no tests detected"}, task_id=ctx.task_id)
        return {"test_run_id": run_id, "outcome": "NO_TESTS", "note": "no test command could be detected", "tried": []}
    d.bus.publish(ctx.mission_id, "test.run_started", ctx.agent_id, {"test_run_id": run_id, "kind": a.kind,
                  "command": " ".join(cands[0]["argv"]), "patch_sha256": sha}, task_id=ctx.task_id)
    tried: list[dict] = []
    art = d.settings.artifacts_dir / ctx.mission_id
    art.mkdir(parents=True, exist_ok=True)
    for cand in cands:
        runner, argv = cand["runner"], list(cand["argv"])
        if runner in disabled:
            tried.append({"runner": runner, "result": "ENV_MISSING_TOOL", "detail": "disabled by mission permissions"})
            continue
        xml = art / f"junit-{run_id}.xml"
        if runner == "pytest":
            argv += ["-p", "no:cacheprovider", f"--junitxml={xml}", *a.scope]
        elif runner == "unittest" and a.scope:
            pass
        t0 = time.monotonic()
        res = await ctx.runner.run(argv, ctx.workspace, a.timeout_s)
        dur = round(time.monotonic() - t0, 3)
        if _env_missing(res, runner):
            tried.append({"runner": runner, "result": "ENV_MISSING_TOOL", "detail": (res.stderr or res.stdout)[-200:]})
            continue
        if res.timed_out:
            parsed = {"total": 0, "failures": [{"test_id": "<run>", "class": "TIMEOUT", "message": f"timed out after {a.timeout_s}s",
                                                "trace_excerpt": res.stdout[-800:], "suspected_files": []}]}
            outcome = "ERROR"
        elif runner == "pytest" and xml.exists():
            parsed = parse_junit(xml.read_text("utf-8"))
            outcome = "GREEN" if parsed["failed"] + parsed["errored"] == 0 and parsed["total"] > 0 else ("NO_TESTS" if parsed["total"] == 0 else "RED")
        elif runner == "pytest" and res.exit_code == 5:
            parsed, outcome = {"total": 0, "failures": []}, "NO_TESTS"
        elif runner == "unittest":
            parsed = parse_unittest(res.stderr + res.stdout)
            outcome = "GREEN" if res.exit_code == 0 and parsed["total"] > 0 else ("NO_TESTS" if parsed["total"] == 0 and res.exit_code == 0 else "RED")
        else:
            text = (res.stdout + res.stderr)[-1500:]
            parsed = {"total": 0, "failures": [{"test_id": "<run>", "class": str(classify(text)), "message": text.strip()[-300:],
                                                "trace_excerpt": text, "suspected_files": []}]}
            outcome = "GREEN" if res.exit_code == 0 else "ERROR"
        enrich_suspects(ctx.workspace, parsed.get("failures", []))
        row = _row(ctx, run_id, a.kind, runner, " ".join(argv[:3]), sha, parsed, outcome, dur)
        fp = fingerprint(row["failures"]) if row["failures"] else None
        evt = "test.passed" if outcome in ("GREEN", "NO_TESTS") else "test.failed"
        d.bus.publish(ctx.mission_id, evt, ctx.agent_id, {
            "test_run_id": run_id, "kind": a.kind, "command": row["command"], "patch_sha256": sha,
            "summary": {k: row[k] for k in ("total", "passed", "failed", "errored", "skipped")},
            "failure_classes": sorted({f["class"] for f in row["failures"]}), "fingerprint": fp, "outcome": outcome,
            "degraded": bool(tried)}, task_id=ctx.task_id)
        return {"test_run_id": run_id, "outcome": outcome, "runner": runner, "command": row["command"], "exit_code": res.exit_code,
                "summary": {k: row[k] for k in ("total", "passed", "failed", "errored", "skipped")}, "duration_s": dur,
                "failures": [{k: f[k] for k in ("test_id", "class", "message", "suspected_files")} | {"trace_excerpt": f["trace_excerpt"][-600:]}
                             for f in row["failures"][:10]], "fingerprint": fp, "tried": tried, "degraded": bool(tried), "patch_sha256": sha}
    row = _row(ctx, run_id, a.kind, "none", "", sha, {"total": 0, "failures": [{"test_id": "<run>", "class": "ENV_MISSING_TOOL",
               "message": "no test runner is available in the sandbox", "trace_excerpt": "", "suspected_files": []}]}, "UNAVAILABLE", 0.0)
    d.bus.publish(ctx.mission_id, "test.failed", ctx.agent_id, {"test_run_id": run_id, "kind": a.kind, "command": "", "patch_sha256": sha,
                  "summary": {"total": 0}, "failure_classes": ["ENV_MISSING_TOOL"], "outcome": "UNAVAILABLE"}, task_id=ctx.task_id)
    raise ToolError("ENV_MISSING_TOOL", "no test runner available", test_run_id=run_id, tried=tried, outcome="UNAVAILABLE")


class CheckArgs(BaseModel):
    timeout_s: int = Field(120, ge=5, le=600)


async def _simple_check(ctx: ToolContext, kind: str, key: str, timeout_s: int) -> dict:
    purge_pycache(ctx.workspace)
    cmd = detect(ctx.workspace)["detected_commands"].get(key)
    sha = (await compute_patch(ctx))[1]
    run_id = new_id("tst")
    if not cmd:
        _row(ctx, run_id, kind, "none", "", sha, {}, "NO_TESTS", 0.0)
        return {"test_run_id": run_id, "skipped": True, "reason": f"no {key} command detected for this repository"}
    if cmd["runner"] in set(ctx.config.get("permissions", {}).get("disabled_tools", [])):
        _row(ctx, run_id, kind, cmd["runner"], "", sha, {}, "UNAVAILABLE", 0.0)
        raise ToolError("ENV_MISSING_TOOL", f"{cmd['runner']} is disabled", test_run_id=run_id)
    t0 = time.monotonic()
    res = await ctx.runner.run(cmd["argv"], ctx.workspace, timeout_s)
    dur = round(time.monotonic() - t0, 3)
    if _env_missing(res, cmd["runner"]):
        _row(ctx, run_id, kind, cmd["runner"], " ".join(cmd["argv"][:3]), sha, {}, "UNAVAILABLE", dur)
        raise ToolError("ENV_MISSING_TOOL", f"{cmd['runner']} is not available", test_run_id=run_id)
    text = (res.stdout + res.stderr).strip()
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    failures = [] if res.exit_code == 0 else [{"test_id": kind.lower(), "class": "LINT" if kind == "LINT" else "BUILD", "message": ln[:300],
                                              "trace_excerpt": "", "suspected_files": []} for ln in lines[:20]]
    outcome = "GREEN" if res.exit_code == 0 else "RED"
    _row(ctx, run_id, kind, cmd["runner"], " ".join(cmd["argv"][:2]), sha, {"total": 1, "passed": int(res.exit_code == 0),
         "failed": int(res.exit_code != 0), "failures": failures}, outcome, dur)
    return {"test_run_id": run_id, "ok": res.exit_code == 0, "outcome": outcome, "exit_code": res.exit_code, "output": text[-1500:]}


async def check_lint(ctx: ToolContext, a: CheckArgs) -> dict:
    return await _simple_check(ctx, "LINT", "lint", a.timeout_s)


async def check_build(ctx: ToolContext, a: CheckArgs) -> dict:
    return await _simple_check(ctx, "BUILD", "build", a.timeout_s)


SPECS = [
    ToolSpec("shell.run", "Run an allowlisted command (no shell; argv only). Prefer dedicated tools when one fits.", ShellArgs, shell_run, "process"),
    ToolSpec("git.status", "Show changed files in the workspace.", NoArgs, git_status),
    ToolSpec("git.diff", "Show the unified patch of all changes vs. the baseline, with its sha256.", DiffArgs, git_diff),
    ToolSpec("git.checkpoint", "Commit the current state as a checkpoint; returns checkpoint_id and patch_sha256.", CheckpointArgs, git_checkpoint, "workspace_write"),
    ToolSpec("git.rollback", "Roll the workspace back to an earlier checkpoint.", RollbackArgs, git_rollback, "workspace_write"),
    ToolSpec("check.test", "Run the project's tests (auto-detected). Optional scope = test paths/ids. Returns structured results.", TestArgs, check_test, "process"),
    ToolSpec("check.lint", "Run the project's linter if one is configured.", CheckArgs, check_lint, "process"),
    ToolSpec("check.build", "Run the project's build/compile check.", CheckArgs, check_build, "process"),
]
