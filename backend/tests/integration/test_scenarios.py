"""Every PS-001 evaluation scenario, run end to end through the real orchestrator (scripted model only)."""
import json
import shutil

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app import evalkit
from app.agents.developer import DeveloperAgent
from app.agents.master import MasterAgent
from app.agents.runtime import AgentRuntime
from app.agents.schemas import CritiqueResponse, DeveloperResult
from app.bootstrap import build_container
from app.common.ids import new_id, now_iso
from app.config import Settings
from app.db import human_requests
from app.services.memory import recall, remember
from app.services.repos import import_repo
from app.state.enums import MasterAction, MessageType, Severity


@pytest.mark.parametrize("sid", list(evalkit.SCENARIOS))
async def test_scenario(sid, tmp_path):
    r = await evalkit.run_scenario(sid, tmp_path)
    failed = [f"{c.name} ({c.detail})" for c in r.checks if not c.ok]
    assert r.ok, f"{sid} failed: {failed}"


@pytest.fixture
def cont(tmp_path):
    return build_container(Settings(DEVPILOT_DATA_DIR=str(tmp_path / "data")), MemorySaver())


async def test_dispute_needs_evidence_and_is_settled_by_a_human(cont, tmp_path):
    c, st = cont, cont.deps.state
    src = tmp_path / "p"
    shutil.copytree(evalkit.SCEN_DIR / "sc-3-failing-test" / "repo", src)
    repo = await import_repo(c.deps, "LOCAL_PATH", str(src))
    m = st.create_mission(repo["id"], "t", "r", {}, "scripted")
    mid = m["id"]
    st.set_criteria(mid, [{"id": "AC-1", "text": "x", "verification": {"method": "command", "argv": ["pytest"]}}], 1)
    task = st.add_task(mid, "IMPLEMENT", "t", files_hint=["calc.py"], criteria_refs=["AC-1"])
    f = st.add_finding(mid, "security", Severity.HIGH, "SQL_INJECTION", "a.py", 3, 3, "x", "fix", 0.9, "fp1", "sha", {"kind": "tool_call", "id": "tcl_x"}, "scanner:changed")
    dev = DeveloperAgent(AgentRuntime(c.deps, c.registry, c.router))

    # a DISPUTE without evidence is rejected: the finding stays OPEN and the master is told
    dev._respond_to_critiques(mid, task["id"], DeveloperResult(summary="s", critique_responses=[CritiqueResponse(finding_id=f["id"], stance="DISPUTE", rationale="false positive")]), [])
    assert [x for x in st.findings(mid) if x["id"] == f["id"]][0]["status"] == "OPEN"
    assert any(x["type"] == "STATUS" and "needs evidence" in x["payload"]["summary"] for x in st.messages(mid))

    # an evidenced DISPUTE is recorded as CRITIQUE_RESPONSE and the finding becomes DISPUTED
    ev = [{"kind": "tool_call", "id": "tcl_proof"}]
    dev._respond_to_critiques(mid, task["id"], DeveloperResult(summary="s", critique_responses=[CritiqueResponse(finding_id=f["id"], stance="DISPUTE", rationale="input is a constant", evidence_refs=ev)]), [])
    assert [x for x in st.findings(mid) if x["id"] == f["id"]][0]["status"] == "DISPUTED"
    assert any(x["type"] == "CRITIQUE_RESPONSE" and x["recipient"] == "security" and x["evidence_refs"] for x in st.messages(mid))

    # the master does not silently resolve it: it escalates with both sides, offering waive / require-fix
    st.set_task_status(task["id"], "READY")
    st.set_task_status(task["id"], "IN_PROGRESS")
    st.set_task_status(task["id"], "IN_REVIEW")
    d = MasterAgent(c.deps).policy(MasterAgent(c.deps).view(mid))
    assert d.action == MasterAction.ESCALATE and "disputes" in d.rationale
    ids = {o["id"] for o in d.extra["options"]}
    assert f"waive_finding:{f['id']}" in ids and "require_fix" in ids

    # human decision: waive -> WAIVED_BY_HUMAN with the reason on record
    req = {"id": new_id("hrq"), "mission_id": mid, "kind": "ESCALATION", "question": d.rationale, "options": d.extra["options"], "evidence_refs": [],
           "status": "OPEN", "answer": None, "created_at": now_iso(), "answered_at": None}
    c.deps.db.insert(human_requests, **req)
    st.set_status(mid, "PLANNING", actor="system")
    st.set_status(mid, "EXECUTING")
    st.set_status(mid, "AWAITING_HUMAN")
    c.runner.orch._apply_answer(mid, req, {"option": f"waive_finding:{f['id']}", "text": "constant input, verified by reading the code"})
    got = [x for x in st.findings(mid) if x["id"] == f["id"]][0]
    assert got["status"] == "WAIVED_BY_HUMAN" and "constant input" in got["waive_reason"]


async def test_replan_limit_escalates_instead_of_looping(cont, tmp_path):
    c, st = cont, cont.deps.state
    src = tmp_path / "p"
    shutil.copytree(evalkit.SCEN_DIR / "sc-3-failing-test" / "repo", src)
    repo = await import_repo(c.deps, "LOCAL_PATH", str(src))
    mid = st.create_mission(repo["id"], "t", "r", {}, "scripted")["id"]
    st.set_criteria(mid, [{"id": "AC-1", "text": "x", "verification": {"method": "command", "argv": ["pytest"]}}], 1)
    st.add_task(mid, "IMPLEMENT", "t", files_hint=["calc.py"])
    st.update_mission(mid, replans=2)
    st.post_message(mid, "developer", "master", MessageType.REPLAN_REQUEST, {"summary": "still wrong"})
    d = MasterAgent(c.deps).policy(MasterAgent(c.deps).view(mid))
    assert d.action == MasterAction.ESCALATE and d.extra["kind"] == "REPLAN_LIMIT"


async def test_memory_is_stored_after_completion_and_recalled_as_hints(tmp_path):
    work = tmp_path
    base = evalkit.SCEN_DIR / "sc-3-failing-test"
    c = build_container(Settings(DEVPILOT_DATA_DIR=str(work / "d")), MemorySaver())
    src = work / "proj"
    shutil.copytree(base / "repo", src)
    repo = await import_repo(c.deps, "LOCAL_PATH", str(src))
    script = json.loads((base / "script.json").read_text())
    m = c.deps.state.create_mission(repo["id"], "Fix calc", "Make the tests pass", {}, "scripted")
    c.router.register_script(m["id"], script)
    c.runner.start(m["id"])
    await c.runner.wait(m["id"], 120)
    sha = c.deps.state.mission(m["id"])["current_patch_sha256"]
    c.runner.resume(m["id"], {"decision": "APPROVED", "patch_sha256": sha, "acknowledged_criteria": [], "publish": {}})
    await c.runner.wait(m["id"], 60)
    assert c.deps.state.mission(m["id"])["status"] == "COMPLETED"
    hints = recall(c.deps, repo["id"])
    assert hints and any("rounded to 1 decimal" in h or "add()" in h for h in hints)
    # a second mission on the same repository sees them in the developer prompt, flagged as unverified hints
    m2 = c.deps.state.create_mission(repo["id"], "Another", "x", {}, "scripted")
    c.deps.state.add_task(m2["id"], "IMPLEMENT", "t")
    prompt = DeveloperAgent(AgentRuntime(c.deps, c.registry, c.router))._prompt(c.deps.state.mission(m2["id"]), c.deps.state.tasks(m2["id"])[0])
    assert "earlier missions" in prompt and "NOT verified" in prompt
    assert remember(c.deps, m["id"]) >= 0
