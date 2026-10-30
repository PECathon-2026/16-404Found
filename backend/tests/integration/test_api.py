"""HTTP-level tests against the real FastAPI app (real orchestrator, tools, verifier); the model is scripted."""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from langgraph.checkpoint.memory import MemorySaver

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
SC3 = ROOT / "eval" / "scenarios" / "sc-3-failing-test"


@pytest.fixture
async def client(tmp_path):
    s = Settings(DEVPILOT_DATA_DIR=str(tmp_path / "data"), DEVPILOT_ALLOW_LOCAL_GIT_URLS="1")
    app = create_app(s, MemorySaver())
    async with LifespanManager(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.app_ = app  # type: ignore[attr-defined]
            yield c


async def wait_status(client, mid, want, timeout=90):
    for _ in range(int(timeout * 10)):
        j = (await client.get(f"/api/v1/missions/{mid}")).json()
        if j["status"] in want:
            return j
        await asyncio.sleep(0.1)
    raise AssertionError(f"timeout waiting for {want}; at {j['status']} ({j['status_reason']})")


async def test_health_config_and_no_provider_guard(client):
    assert (await client.get("/api/v1/health")).json()["status"] == "ok"
    cfg = (await client.get("/api/v1/config/models")).json()
    assert cfg["live_available"] is False and cfg["sandbox_mode"] == "local_jail"
    repo = await client.post("/api/v1/repositories", json={"source_type": "LOCAL_PATH", "source_ref": str(SC3 / "repo")})
    assert repo.status_code == 201
    r = await client.post("/api/v1/missions", json={"title": "x", "prompt": "y", "repository_id": repo.json()["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_MODEL_PROVIDER"
    assert (await client.get("/api/v1/missions/mis_nope")).status_code == 404


async def test_repository_import_guards(client):
    for ref in ("/", "/etc", "/etc/ssh", "/usr/bin", str(Path.home()), str(Path.home() / ".ssh"), "/private/etc"):
        r = await client.post("/api/v1/repositories", json={"source_type": "LOCAL_PATH", "source_ref": ref})
        assert r.status_code == 400 or "not a directory" in r.text, (ref, r.text)
    r = await client.post("/api/v1/repositories", json={"source_type": "GIT_URL", "source_ref": "https://evil.example/o/r"})
    assert r.status_code == 400 and "github.com" in r.json()["error"]["message"]
    assert (await client.get("/api/v1/repositories/parse", params={"url": "https://github.com/a/b"})).json() == {"valid": True, "owner": "a", "name": "b"}
    assert (await client.get("/api/v1/repositories/parse", params={"url": "https://github.com.evil.io/a/b"})).json()["valid"] is False


async def test_demo_mission_full_flow_over_http(client):
    sc = (await client.get("/api/v1/demo/scenarios")).json()["scenarios"]
    assert any(s["id"] == "sc-3-failing-test" for s in sc)
    created = await client.post("/api/v1/demo/missions", json={"scenario_id": "sc-3-failing-test"})
    assert created.status_code == 201 and created.json()["mode"] == "scripted"
    mid = created.json()["id"]
    j = await wait_status(client, mid, {"AWAITING_APPROVAL", "FAILED"})
    assert j["status"] == "AWAITING_APPROVAL", j["status_reason"]
    assert j["gate"]["clear"] is True and [c["status"] for c in j["acceptance_criteria"]] == ["PASS"] * 3

    tasks = (await client.get(f"/api/v1/missions/{mid}/tasks")).json()["tasks"]
    assert {t["kind"] for t in tasks} >= {"IMPLEMENT", "REPAIR", "RUN_CHECKS", "SECURITY_REVIEW"}
    diffs = (await client.get(f"/api/v1/missions/{mid}/diffs")).json()
    assert [f["path"] for f in diffs["files"]] == ["calc.py"] and "a + b" in diffs["files"][0]["modified"] and "a - b" in diffs["files"][0]["original"]
    patch = (await client.get(f"/api/v1/missions/{mid}/patch")).text
    assert "diff --git a/calc.py" in patch
    runs = (await client.get(f"/api/v1/missions/{mid}/test-runs")).json()["runs"]
    assert runs[0]["kind"] == "BASELINE" and runs[0]["outcome"] == "RED"
    assert (await client.get(f"/api/v1/missions/{mid}/verification")).json()["verification"]["overall"] == "PASS"
    assert len((await client.get(f"/api/v1/missions/{mid}/decisions")).json()["decisions"]) >= 6
    msgs = (await client.get(f"/api/v1/missions/{mid}/messages", params={"type": "CRITIQUE"})).json()["messages"]
    assert msgs and all(m["evidence_refs"] for m in msgs)
    logs = (await client.get(f"/api/v1/missions/{mid}/logs", params={"tool": "fs.edit"})).json()["tool_calls"]
    assert len(logs) == 2
    tcl = (await client.get(f"/api/v1/missions/{mid}/tool-calls/{logs[0]['id']}")).json()
    assert tcl["tool"] == "fs.edit"
    m = (await client.get(f"/api/v1/missions/{mid}/metrics")).json()
    assert m["distinct_developer_tools"] >= 3 and m["cost_usd"] is None and m["repair_cycles"] >= 1

    # approvals: wrong state / stale hash / bad decision are refused with the documented codes
    sha = j["current_patch_sha256"]
    stale = await client.post(f"/api/v1/missions/{mid}/approvals", json={"decision": "APPROVED", "patch_sha256": "0" * 64})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_PATCH"
    nocomment = await client.post(f"/api/v1/missions/{mid}/approvals", json={"decision": "CHANGES_REQUESTED", "patch_sha256": sha})
    assert nocomment.status_code == 422
    pub = await client.post(f"/api/v1/missions/{mid}/approvals", json={"decision": "APPROVED", "patch_sha256": sha, "publish": {"push": True}})
    assert pub.status_code == 422 and pub.json()["error"]["code"] == "PUBLISH_UNSUPPORTED"  # push only for GitHub-imported repos
    ok = await client.post(f"/api/v1/missions/{mid}/approvals", json={"decision": "APPROVED", "patch_sha256": sha, "comment": "lgtm"})
    assert ok.status_code == 200
    done = await wait_status(client, mid, {"COMPLETED", "FAILED"})
    assert done["status"] == "COMPLETED" and done["outcome"]["terminal_status"] == "COMPLETED"
    assert (await client.post(f"/api/v1/missions/{mid}/approvals", json={"decision": "APPROVED", "patch_sha256": sha})).status_code == 409
    rep = await client.get(f"/api/v1/missions/{mid}/report", params={"format": "md"})
    assert "Verified" in rep.text and "Unverified agent claims" in rep.text
    ev = (await client.get(f"/api/v1/missions/{mid}/replay")).json()["events"]
    ids = [e["id"] for e in ev]
    assert ids == sorted(ids) and ev[0]["type"] == "mission.created" and ev[-1]["type"] == "mission.completed"
    # rollback restores the original (local path) source
    rb = await client.post(f"/api/v1/missions/{mid}/rollback")
    assert rb.status_code == 200
    repo_path = Path(done["repository"]["source_ref"])
    assert "a - b" in (repo_path / "calc.py").read_text()


async def test_pause_resume_cancel_and_illegal_transitions(client):
    created = await client.post("/api/v1/demo/missions", json={"scenario_id": "sc-3-failing-test", "start": False})
    mid = created.json()["id"]
    assert (await client.post(f"/api/v1/missions/{mid}/resume")).status_code == 409  # not paused
    r = await client.post(f"/api/v1/missions/{mid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert (await client.post(f"/api/v1/missions/{mid}/cancel")).status_code == 200  # idempotent on terminal
    assert (await client.post(f"/api/v1/missions/{mid}/pause")).status_code == 409


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


async def test_github_style_flow_clone_branch_commit_and_push(client, tmp_path):
    """Clone a repo by URL -> mission on a DevPilot-owned clone -> approve with push -> a NEW branch lands on the remote."""
    work = tmp_path / "seed"
    shutil.copytree(SC3 / "repo", work)
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "a@b.c")
    _git(work, "config", "user.name", "seed")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "seed")
    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(remote))

    imp = await client.post("/api/v1/repositories", json={"source_type": "GIT_URL", "source_ref": str(remote)})
    assert imp.status_code == 201, imp.text
    repo = imp.json()
    assert repo["default_branch"] == "main" and repo["source_type"] == "GIT_URL"

    # mission on the imported repo using the scenario script (scripted model)
    app = client.app_
    c = app.state.c
    m = c.deps.state.create_mission(repo["id"], "Fix calc", "Make the tests pass", {}, "scripted")
    c.router.register_script(m["id"], json.loads((SC3 / "script.json").read_text()))
    c.runner.start(m["id"])
    j = await wait_status(client, m["id"], {"AWAITING_APPROVAL", "FAILED"})
    assert j["status"] == "AWAITING_APPROVAL", j["status_reason"]

    ok = await client.post(f"/api/v1/missions/{m['id']}/approvals", json={
        "decision": "APPROVED", "patch_sha256": j["current_patch_sha256"], "publish": {"push": True}})
    assert ok.status_code == 200, ok.text
    done = await wait_status(client, m["id"], {"COMPLETED", "FAILED"})
    assert done["status"] == "COMPLETED", done["status_reason"]
    applied = done["outcome"]["applied"]
    assert applied["pushed"] is True and applied["branch"].startswith("devpilot/")
    branches = _git(remote, "branch", "--format=%(refname:short)").split()
    assert applied["branch"] in branches
    assert "a + b" in _git(remote, "show", f"{applied['branch']}:calc.py")
    assert "a - b" in _git(remote, "show", "main:calc.py"), "the default branch must be untouched"
    log = _git(remote, "log", "--format=%an|%s", "-1", applied["branch"])
    assert log.startswith("DevPilot|Fix calc")


async def test_push_without_flag_never_pushes(client, tmp_path):
    work = tmp_path / "seed"
    shutil.copytree(SC3 / "repo", work)
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "a@b.c"], ["config", "user.name", "s"], ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        _git(work, *a)
    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(remote))
    repo = (await client.post("/api/v1/repositories", json={"source_type": "GIT_URL", "source_ref": str(remote)})).json()
    c = client.app_.state.c
    m = c.deps.state.create_mission(repo["id"], "Fix calc", "x", {}, "scripted")
    c.router.register_script(m["id"], json.loads((SC3 / "script.json").read_text()))
    c.runner.start(m["id"])
    j = await wait_status(client, m["id"], {"AWAITING_APPROVAL", "FAILED"})
    await client.post(f"/api/v1/missions/{m['id']}/approvals", json={"decision": "APPROVED", "patch_sha256": j["current_patch_sha256"]})
    done = await wait_status(client, m["id"], {"COMPLETED", "FAILED"})
    assert done["status"] == "COMPLETED" and "pushed" not in done["outcome"]["applied"] and done["outcome"]["applied"]["branch"].startswith("devpilot/")
    assert _git(remote, "branch", "--format=%(refname:short)").split() == ["main"], "nothing may be pushed unless the approval opted in"


async def test_file_tree_and_content_are_real_jailed_and_redacted(client):
    created = await client.post("/api/v1/demo/missions", json={"scenario_id": "sc-4-security"})
    mid = created.json()["id"]
    j = await wait_status(client, mid, {"AWAITING_APPROVAL", "FAILED"})
    assert j["status"] == "AWAITING_APPROVAL"
    tree = (await client.get(f"/api/v1/missions/{mid}/files")).json()
    by = {f["path"]: f for f in tree["files"]}
    assert by["users.py"]["change"] == "MODIFY" and by["tests/test_email.py"]["change"] == "ADD" and by["README.md"]["change"] is None
    assert not any(p.startswith(".git") for p in by)
    ok = (await client.get(f"/api/v1/missions/{mid}/files/content", params={"path": "users.py"})).json()
    assert "find_by_email" in ok["content"]
    for bad in ("../../etc/passwd", "/etc/passwd", ".git/config"):
        assert (await client.get(f"/api/v1/missions/{mid}/files/content", params={"path": bad})).status_code == 403, bad
    await client.post(f"/api/v1/missions/{mid}/cancel")


async def test_per_test_cases_are_real(client):
    created = await client.post("/api/v1/demo/missions", json={"scenario_id": "sc-3-failing-test"})
    mid = created.json()["id"]
    await wait_status(client, mid, {"AWAITING_APPROVAL", "FAILED"})
    runs = (await client.get(f"/api/v1/missions/{mid}/test-runs")).json()["runs"]
    base = next(r for r in runs if r["kind"] == "BASELINE")
    got = (await client.get(f"/api/v1/missions/{mid}/test-runs/{base['id']}/cases")).json()
    assert got["available"] and {c["status"] for c in got["cases"]} == {"PASSED", "FAILED"}
    assert sum(c["status"] == "FAILED" for c in got["cases"]) == base["failed"] and len(got["cases"]) == base["total"]
    assert (await client.get(f"/api/v1/missions/{mid}/test-runs/..%2Fx/cases")).status_code in (200, 404)
    await client.post(f"/api/v1/missions/{mid}/cancel")
