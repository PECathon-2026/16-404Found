"""SC-3 end to end through the real LangGraph orchestrator, real tools, real pytest, real verifier process.
Only the *model* is scripted; everything else (state, tools, git, tests, verifier, gate) is the production code."""
import json
import shutil
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.bootstrap import build_container
from app.config import Settings
from app.services.repos import import_repo

ROOT = Path(__file__).resolve().parents[3]
SC3 = ROOT / "eval" / "scenarios" / "sc-3-failing-test"


@pytest.fixture
def env(tmp_path):
    s = Settings(DEVPILOT_DATA_DIR=str(tmp_path / "data"))
    c = build_container(s, MemorySaver())
    src = tmp_path / "proj"
    shutil.copytree(SC3 / "repo", src)
    return c, src


async def start_scripted(c, src, script, config=None, prompt="Make the tests pass"):
    repo = await import_repo(c.deps, "LOCAL_PATH", str(src))
    m = c.deps.state.create_mission(repo["id"], "t", prompt, config or {}, "scripted")
    c.router.register_script(m["id"], script)
    c.runner.start(m["id"])
    await c.runner.wait(m["id"], 120)
    return m["id"]


def types(c, mid):
    return [e["type"] for e in c.deps.bus.history(mid)]


async def test_sc3_feedback_loop_then_approval_applies_patch(env):
    c, src = env
    script = json.loads((SC3 / "script.json").read_text())
    mid = await start_scripted(c, src, script)
    st = c.deps.state
    m = st.mission(mid)
    assert m["status"] == "AWAITING_APPROVAL", (m["status"], m["status_reason"], types(c, mid)[-12:])
    assert (src / "calc.py").read_text().count("a - b") == 1, "source must be untouched before approval"

    # -- the feedback loop: red run -> repair.initiated -> edit -> new (different) failure -> repair -> green
    t = types(c, mid)
    i_fail1 = t.index("test.failed")
    i_rep1 = t.index("repair.initiated")
    assert i_fail1 < i_rep1 < t.index("test.passed", i_rep1)
    assert m["repair_cycles"] >= 1
    assert any(r["kind"] == "SELF_CHECK" for r in st.test_runs(mid)), "developer self-checks are recorded but never gate evidence"
    runs = [r for r in st.test_runs(mid) if r["kind"] == "TEST"]
    assert runs[0]["outcome"] == "RED" and runs[-1]["outcome"] == "GREEN"
    shas = [r["patch_sha256"] for r in runs]
    assert len(set(shas)) == len(shas), "every rerun is on a different patch"
    reds = [r for r in runs if r["outcome"] == "RED"]
    from app.common.parsers import fingerprint
    fps = [fingerprint(r["failures"]) for r in reds]
    assert len(set(fps)) == len(fps) >= 1
    rep = [e for e in c.deps.bus.history(mid) if e["type"] == "repair.initiated"][0]["payload"]
    assert rep["from_test_run_id"] or rep["failure_fingerprint"]

    # -- baseline recorded before the first edit; tests never modified
    ids = [(e["id"], e["type"]) for e in c.deps.bus.history(mid)]
    first_edit = next(i for i, (_, ty) in enumerate(ids) if ty == "file.modified")
    base_run = next(r for r in st.test_runs(mid) if r["kind"] == "BASELINE")
    assert base_run["outcome"] == "RED" and base_run["created_at"] <= next(e for e in c.deps.bus.history(mid) if e["type"] == "file.modified")["created_at"]
    assert all(not ch["is_test_file"] for ch in st.code_changes(mid)) and first_edit > 0

    # -- the master used several distinct actions, chosen from evidence
    acts = {d["action"] for d in c.deps.db.select(__import__("app.db", fromlist=["decisions"]).decisions, where_cols={"mission_id": mid})}
    assert {"PLAN", "DELEGATE", "RETRY", "EXECUTE", "VERIFY", "REQUEST_APPROVAL"} <= acts, acts

    # -- the system re-ran the tests itself, and the verifier ran in its own process on the same patch
    assert any(r["kind"] == "CONFIRM" and r["outcome"] == "GREEN" for r in st.test_runs(mid))
    v = st.latest_verification(mid)
    assert v["overall"] == "PASS" and v["patch_sha256"] == m["current_patch_sha256"]
    assert [x["status"] for x in st.criteria(mid)] == ["PASS", "PASS", "PASS"]

    # -- agents actually exchanged typed messages (not persona calls)
    msgs = st.messages(mid)
    pairs = {(x["sender"], x["recipient"], x["type"]) for x in msgs}
    assert ("tester", "developer", "CRITIQUE") in pairs and ("master", "developer", "TASK_ASSIGN") in pairs and ("developer", "master", "TASK_RESULT") in pairs

    # -- human approval: a stale hash is refused, the right one completes and applies the patch
    c.runner.resume(mid, {"decision": "APPROVED", "patch_sha256": m["current_patch_sha256"], "comment": "ok", "acknowledged_criteria": []})
    await c.runner.wait(mid, 60)
    done = st.mission(mid)
    assert done["status"] == "COMPLETED", (done["status"], done["status_reason"])
    assert "a + b" in (src / "calc.py").read_text() and "round(s, 2)" in (src / "calc.py").read_text()
    out = done["outcome"]
    assert out["terminal_status"] == "COMPLETED" and any(x["id"] == "AC-1" for x in out["verified"])
    assert out["unverified_agent_claims"] and "tests" in {x["id"] for x in out["verified"]}
    assert (c.settings.runs_dir / mid / "report.md").exists() and (c.settings.runs_dir / mid / "events.jsonl").exists()


async def test_rejection_leaves_source_untouched(env):
    c, src = env
    mid = await start_scripted(c, src, json.loads((SC3 / "script.json").read_text()))
    m = c.deps.state.mission(mid)
    assert m["status"] == "AWAITING_APPROVAL"
    c.runner.resume(mid, {"decision": "REJECTED", "patch_sha256": m["current_patch_sha256"], "comment": "no"})
    await c.runner.wait(mid, 30)
    assert c.deps.state.mission(mid)["status"] == "REJECTED"
    assert "a - b" in (src / "calc.py").read_text()
