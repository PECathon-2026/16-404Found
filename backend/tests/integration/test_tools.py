"""Tools run against a real workspace: real git, real pytest in the local-jail runner."""
import pytest

from tests.conftest import CALC


async def call(reg, ctx, name, **args):
    return await reg.call(ctx, name, args)


async def test_read_search_edit_checkpoint_flow(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files)
    r = await call(registry, ctx, "fs.search", pattern="def divide")
    assert r.ok and r.data["matches"][0]["path"] == "calc.py"
    r = await call(registry, ctx, "fs.read", path="calc.py")
    assert r.ok and "return a + b" in r.data["content"]
    r = await call(registry, ctx, "fs.edit", path="calc.py", edits=[{"old": "return a + b", "new": "return a + b  # sum"}])
    assert r.ok and r.data["patch_sha256"] and r.data["additions"] == 1
    sha1 = r.data["patch_sha256"]
    r = await call(registry, ctx, "git.checkpoint", message="cp1")
    assert r.ok and r.data["patch_sha256"] == sha1
    d = ctx.deps.state.mission(ctx.mission_id)
    assert d["current_patch_sha256"] == sha1
    # events + tool_calls persisted
    types = [e["type"] for e in ctx.deps.bus.history(ctx.mission_id)]
    assert "tool.called" in types and "tool.completed" in types and "file.modified" in types
    assert len(ctx.deps.state.tool_calls(ctx.mission_id)) == 4


async def test_edit_conflicts_force_reread(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files)
    r = await call(registry, ctx, "fs.edit", path="calc.py", edits=[{"old": "does not exist", "new": "x"}])
    assert not r.ok and r.error["code"] == "CONFLICT"
    r = await call(registry, ctx, "fs.edit", path="calc.py", edits=[{"old": "return", "new": "return  "}])
    assert not r.ok and "matches 2" in r.error["message"]


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/hosts", ".git/config", "~/x"])
async def test_fs_tools_are_jailed(registry, make_ctx, calc_files, path):
    ctx = await make_ctx(calc_files)
    for tool, args in (("fs.read", {"path": path}), ("fs.create", {"path": path, "content": "x"})):
        r = await call(registry, ctx, tool, **args)
        assert not r.ok and r.error["code"] == "POLICY_DENIED", (tool, path, r.error)


async def test_existing_tests_are_protected_outside_write_tests(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files, task_kind="REPAIR")
    r = await call(registry, ctx, "fs.edit", path="tests/test_calc.py", edits=[{"old": "== 3", "new": "== 4"}])
    assert not r.ok and r.error["code"] == "POLICY_DENIED" and "existing test" in r.error["message"]
    r = await call(registry, ctx, "fs.delete", path="tests/test_calc.py")
    assert not r.ok and r.error["code"] == "POLICY_DENIED"
    # new test files are fine
    r = await call(registry, ctx, "fs.create", path="tests/test_new.py", content="def test_n():\n    assert True\n")
    assert r.ok and r.data["is_test_file"] and not r.data["tamper_flags"]
    # events: policy.denied logged
    assert any(e["type"] == "policy.denied" for e in ctx.deps.bus.history(ctx.mission_id))


async def test_write_tests_task_may_edit_but_weakening_is_flagged(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files, task_kind="WRITE_TESTS")
    r = await call(registry, ctx, "fs.edit", path="tests/test_calc.py",
                   edits=[{"old": "    assert add(1, 2) == 3", "new": "    pass\n\n\n@pytest.mark.skip\ndef test_skipped():\n    pass"}])
    assert r.ok and "REMOVED_LINES" in r.data["tamper_flags"]
    findings = ctx.deps.state.findings(ctx.mission_id)
    assert findings and findings[0]["category"] == "TEST_TAMPERING" and findings[0]["severity"] == "HIGH"


async def test_permission_matrix_denies(registry, make_ctx, calc_files):
    sec = await make_ctx(calc_files, agent="security")
    assert (await call(registry, sec, "fs.edit", path="calc.py", edits=[{"old": "a", "new": "b"}])).error["code"] == "POLICY_DENIED"
    assert (await call(registry, sec, "shell.run", command="ls")).error["code"] == "POLICY_DENIED"
    master = await make_ctx(calc_files, agent="master")
    assert (await call(registry, master, "fs.read", path="calc.py")).error["code"] == "POLICY_DENIED"
    tester = await make_ctx(calc_files, agent="tester")
    r = await call(registry, tester, "fs.edit", path="calc.py", edits=[{"old": "a + b", "new": "a - b"}])
    assert r.error["code"] == "POLICY_DENIED" and "only change test files" in r.error["message"]


async def test_shell_policy_and_execution(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files)
    ok = await call(registry, ctx, "shell.run", command="git status")
    assert ok.ok and ok.data["exit_code"] == 0
    for bad in ("rm -rf .", "curl http://x", "cat /etc/passwd", "ls; id", "git push"):
        r = await call(registry, ctx, "shell.run", command=bad)
        assert not r.ok and r.error["code"] == "POLICY_DENIED", bad
    assert (ctx.workspace / "calc.py").exists()


async def test_check_test_green_and_red_with_classification(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files)
    r = await call(registry, ctx, "check.test", kind="BASELINE")
    assert r.ok and r.data["outcome"] == "GREEN" and r.data["summary"]["total"] == 3
    await call(registry, ctx, "fs.edit", path="calc.py", edits=[{"old": "return a + b", "new": "return a - b"}])
    r = await call(registry, ctx, "check.test")
    assert r.ok and r.data["outcome"] == "RED"
    f = r.data["failures"][0]
    assert f["class"] == "ASSERTION" and "calc.py" in f["suspected_files"] and r.data["fingerprint"].startswith("sha1:")
    evts = [e["type"] for e in ctx.deps.bus.history(ctx.mission_id)]
    assert "test.run_started" in evts and "test.failed" in evts and "test.passed" in evts
    runs = ctx.deps.state.test_runs(ctx.mission_id)
    assert [x["kind"] for x in runs] == ["BASELINE", "SELF_CHECK"] and runs[0]["patch_sha256"] is None and runs[1]["patch_sha256"]  # developer runs never count as gate evidence
    tester = await make_ctx(calc_files, agent="tester")
    assert (await call(registry, tester, "check.test")).ok and tester.deps.state.test_runs(tester.mission_id)[-1]["kind"] == "TEST"
    scoped = await call(registry, tester, "check.test", scope=["tests/test_calc.py"])
    assert scoped.ok and tester.deps.state.test_runs(tester.mission_id)[-1]["kind"] == "SELF_CHECK"  # scoped => not gate evidence


async def test_unavailable_test_tool_falls_back_and_is_reported(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files, config={"permissions": {"disabled_tools": ["pytest"]}})
    r = await call(registry, ctx, "check.test")
    # pytest-style tests still run under unittest discovery only if they are unittest-compatible; here they are not,
    # so the point is: degraded evidence is reported, never a fabricated pass.
    assert r.data is None or r.data["degraded"]
    ctx2 = await make_ctx({"calc.py": CALC, "test_u.py": "import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(add(1,2),3)\n"},
                          config={"permissions": {"disabled_tools": ["pytest"]}})
    r2 = await call(registry, ctx2, "check.test")
    assert r2.ok and r2.data["runner"] == "unittest" and r2.data["degraded"] and r2.data["tried"][0]["result"] == "ENV_MISSING_TOOL"
    assert r2.data["outcome"] == "GREEN"
    # tests exist but *every* runner is unavailable: reported as UNAVAILABLE, recorded, never a pass
    none = await make_ctx(ctx2_files := {"calc.py": CALC, "test_u.py": "def test_a():\n    assert True\n"},
                          config={"permissions": {"disabled_tools": ["pytest", "unittest"]}})
    r3 = await call(registry, none, "check.test")
    assert not r3.ok and r3.error["code"] == "ENV_MISSING_TOOL" and r3.error["outcome"] == "UNAVAILABLE"
    assert none.deps.state.test_runs(none.mission_id)[-1]["outcome"] == "UNAVAILABLE"
    # genuinely no tests: NO_TESTS (ok, but the gate treats it separately)
    empty = await make_ctx({"calc.py": CALC})
    r4 = await call(registry, empty, "check.test")
    assert r4.ok and r4.data["outcome"] == "NO_TESTS"
    _ = ctx2_files


async def test_workspace_behind_a_symlink_works(registry, make_ctx, calc_files, tmp_path):
    """Regression: data dir reached through a symlink (macOS /var -> /private/var) crashed fs.list/fs.search."""
    ctx = await make_ctx(calc_files)
    link = tmp_path / "linked"
    link.symlink_to(ctx.workspace)
    ctx.workspace = link  # type: ignore[assignment]  (simulate a context built from an unresolved path)
    from app.tools.base import ToolContext
    ctx2 = ToolContext(deps=ctx.deps, mission_id=ctx.mission_id, agent_id="developer", workspace=link, runner=ctx.runner, base_commit=ctx.base_commit)
    for tool, args in (("fs.list", {}), ("fs.search", {"pattern": "def add"}), ("fs.read", {"path": "calc.py"})):
        r = await registry.call(ctx2, tool, args)
        assert r.ok, (tool, r.error)


async def test_parallel_git_operations_do_not_race(registry, make_ctx, calc_files):
    """tester || security call git concurrently on one workspace; index.lock contention used to corrupt results."""
    import asyncio

    ctx = await make_ctx(calc_files)
    await registry.call(ctx, "fs.edit", {"path": "calc.py", "edits": [{"old": "return a + b", "new": "return a + b  # x"}]})
    results = await asyncio.gather(*[registry.call(ctx, "git.diff", {}) for _ in range(12)], *[registry.call(ctx, "git.status", {}) for _ in range(12)])
    assert all(r.ok for r in results), [r.error for r in results if not r.ok][:2]
    assert len({r.data["patch_sha256"] for r in results if "patch_sha256" in (r.data or {})}) == 1


async def test_same_size_edits_in_the_same_second_never_run_stale_bytecode(registry, make_ctx, calc_files):
    """Regression for a flaky e2e failure: compileall wrote a .pyc, then a same-size edit within the same second
    left Python executing the OLD code. Flip a same-size edit repeatedly, building + testing between each."""
    tester = await make_ctx(calc_files, agent="tester")
    dev = await make_ctx(calc_files)
    dev.workspace, dev.mission_id, dev.base_commit = tester.workspace, tester.mission_id, tester.base_commit  # same workspace AND repo, two agents
    state = "a + b"
    for _ in range(6):
        new = "a - b" if state == "a + b" else "a + b"
        r = await registry.call(dev, "fs.edit", {"path": "calc.py", "edits": [{"old": f"return {state}", "new": f"return {new}"}]})
        assert r.ok, r.error
        state = new
        assert (await registry.call(tester, "check.build", {})).ok
        t = await registry.call(tester, "check.test", {})
        expected = "GREEN" if state == "a + b" else "RED"
        assert t.data["outcome"] == expected, f"stale bytecode: file says {state!r} but tests reported {t.data['outcome']}"


async def test_build_check_reports_syntax_errors_without_writing_bytecode(registry, make_ctx):
    ctx = await make_ctx({"ok.py": "x = 1\n", "bad.py": "def f(:\n    pass\n"}, agent="tester")
    r = await registry.call(ctx, "check.build", {})
    assert r.ok and r.data["outcome"] == "RED" and "bad.py" in r.data["output"]
    assert not list(ctx.workspace.rglob("*.pyc")), "the build check must not write bytecode"
