"""The verifier is a separate process and must not trust or even see the developer's claims."""
import json
import subprocess
import sys
from pathlib import Path

from app.sandbox.git import git
from app.services.verification import run_verification
from app.tools.ws import compute_patch
from tests.conftest import CALC, TEST_CALC

BACKEND = Path(__file__).resolve().parents[2]


async def _criteria(deps, ctx, items):
    deps.state.set_criteria(ctx.mission_id, items, 1)


async def test_verifier_passes_a_correct_patch_and_fails_a_broken_one(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files)
    d = ctx.deps
    new_test = "from calc import add\n\n\ndef test_add_negative():\n    assert add(-1, -2) == -3\n"
    await registry.call(ctx, "fs.create", {"path": "tests/test_extra.py", "content": new_test})
    await registry.call(ctx, "fs.edit", {"path": "calc.py", "edits": [{"old": "return a + b", "new": "return a + b  # ok"}]})
    await _criteria(d, ctx, [
        {"id": "AC-1", "text": "negative add works", "verification": {"method": "test_selector", "selectors": ["tests/test_extra.py"]}},
        {"id": "AC-2", "text": "suite passes", "verification": {"method": "command", "argv": ["python", "-m", "pytest", "-q"]}},
        {"id": "AC-3", "text": "comment present", "verification": {"method": "static_check", "path": "calc.py", "must_match": "# ok"}},
        {"id": "AC-4", "text": "reads well", "verification": {"method": "manual_review", "rubric": "clear"}},
    ])
    rep = await run_verification(d, ctx)
    st = {r["ac_id"]: r["status"] for r in rep["results"]}
    assert st == {"AC-1": "PASS", "AC-2": "PASS", "AC-3": "PASS", "AC-4": "INCONCLUSIVE"}, rep
    assert rep["overall"] == "INCONCLUSIVE" and rep["regression_check"]["new_failures"] == []
    assert d.state.latest_verification(ctx.mission_id)["overall"] == "INCONCLUSIVE"
    assert [c["status"] for c in d.state.criteria(ctx.mission_id)] == ["PASS", "PASS", "PASS", "INCONCLUSIVE"]

    # sabotage: a broken patch; the developer "claims" success (we never pass the claim in) -> verifier FAIL
    await registry.call(ctx, "fs.edit", {"path": "calc.py", "edits": [{"old": "return a + b  # ok", "new": "return a - b"}]})
    rep2 = await run_verification(d, ctx)
    assert rep2["overall"] == "FAIL" and rep2["regression_check"]["new_failures"], rep2
    assert {r["ac_id"]: r["status"] for r in rep2["results"]}["AC-2"] == "FAIL"


async def test_verifier_detects_tampering_and_regressions(registry, make_ctx, calc_files):
    ctx = await make_ctx(calc_files, task_kind="WRITE_TESTS")
    await registry.call(ctx, "fs.edit", {"path": "tests/test_calc.py", "edits": [{"old": "assert add(1, 2) == 3", "new": "assert True"}]})
    await registry.call(ctx, "fs.edit", {"path": "calc.py", "edits": [{"old": "return a + b", "new": "return 0"}]})
    ctx.deps.state.set_criteria(ctx.mission_id, [{"id": "AC-1", "text": "x", "verification": {"method": "command", "argv": ["python", "-m", "pytest", "-q"]}}], 1)
    rep = await run_verification(ctx.deps, ctx)
    assert rep["tamper_check"]["modified_existing_tests"] == ["tests/test_calc.py"]
    assert rep["overall"] in ("PASS", "FAIL")  # suite is green because the test was weakened - tamper_check is what blocks the gate


async def test_verifier_crash_is_inconclusive_never_pass(registry, make_ctx, calc_files, monkeypatch):
    ctx = await make_ctx(calc_files)
    await registry.call(ctx, "fs.edit", {"path": "calc.py", "edits": [{"old": "return a + b", "new": "return a + b  # x"}]})
    ctx.deps.state.set_criteria(ctx.mission_id, [{"id": "AC-1", "text": "x", "verification": {"method": "command", "argv": ["python", "-m", "pytest", "-q"]}}], 1)
    monkeypatch.setattr("app.services.verification.sys.executable", "/nonexistent/python")
    rep = await run_verification(ctx.deps, ctx)
    assert rep["overall"] == "INCONCLUSIVE" and rep["error"]


def test_verifier_module_isolation():
    """Importing the verifier must not pull in agents, graph, db, deps or the state manager."""
    code = ("import sys, app.verifier.main; bad=[m for m in sys.modules if m.split('.')[:2] in "
            "(['app','agents'],['app','graph'],['app','db'],['app','deps'],['app','state']) and m not in ('app.state','app.state.enums')]; "
            "print(json.dumps(bad))")
    out = subprocess.run([sys.executable, "-c", "import json;" + code], cwd=BACKEND, capture_output=True, text=True, env={"PYTHONPATH": str(BACKEND), "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []
    _ = (git, compute_patch, CALC, TEST_CALC)
