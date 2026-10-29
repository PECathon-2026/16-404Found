"""REST + SSE API (ARCHITECTURE.md §E). Controllers validate and delegate; no orchestration logic lives here."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ...agents.context import make_ctx
from ...agents.master import MasterAgent
from ...bootstrap import Container
from ...common.ids import new_id, now_iso
from ...common.tamper import analyze_patch
from ...db import agent_executions, decisions, human_requests, missions, repositories, tool_calls
from ...sandbox.git import GitError, git
from ...services import publish, reports
from ...services.repos import RepoError, import_repo, parse_github_url
from ...state.enums import TERMINAL_STATUSES
from ...state.enums import MissionStatus as S
from ...state.manager import StateError
from ...state.transitions import IllegalTransition
from ...tools.ws import compute_patch

EVAL_DIR = Path(__file__).resolve().parents[4] / "eval" / "scenarios"


class RepoCreate(BaseModel):
    name: str | None = None
    source_type: Literal["LOCAL_PATH", "GIT_URL"]
    source_ref: str
    branch: str | None = None
    github_token: str | None = Field(default=None, description="Used for this clone only; never stored or logged")


class MissionCreate(BaseModel):
    title: str
    prompt: str
    repository_id: str
    config: dict[str, Any] = {}
    start: bool = False


class DemoCreate(BaseModel):
    scenario_id: str
    start: bool = True


class RespondReq(BaseModel):
    request_id: str
    option: str | None = None
    text: str | None = None


class PublishOpts(BaseModel):
    push: bool = False
    open_pr: bool = False
    github_token: str | None = None


class ApprovalReq(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "CHANGES_REQUESTED"]
    patch_sha256: str
    comment: str | None = None
    acknowledged_criteria: list[str] = []
    publish: PublishOpts = PublishOpts()


class WaiveReq(BaseModel):
    reason: str = Field(min_length=3)


def err(status: int, code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "details": details})


def public_repo(r: dict[str, Any]) -> dict[str, Any]:
    return {k: r[k] for k in ("id", "name", "source_type", "source_ref", "default_branch", "language_hints", "head_commit", "detected_commands",
                              "github_owner", "github_name", "created_at")}


def build_router(c: Container) -> APIRouter:
    r = APIRouter(prefix="/api/v1")
    d, st, bus = c.deps, c.deps.state, c.deps.bus
    master = MasterAgent(d)

    def get_mission(mid: str) -> dict[str, Any]:
        try:
            return st.mission(mid)
        except StateError:
            raise err(404, "NOT_FOUND", f"mission {mid} not found") from None

    # ---------------------------------------------------------------- misc
    @r.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "time": now_iso()}

    @r.get("/config/models")
    async def config_models() -> dict[str, Any]:
        import os
        is_docker = Path("/.dockerenv").exists() or bool(os.environ.get("DOCKER_CONTAINER"))
        mode = "container_isolated" if is_docker else "local_jail"
        note = ("Container-isolated sandbox: running within an isolated Docker container with non-root privileges (uid 10001), "
                "path jail enforcement, CPU/memory rlimits, scrubbed environment, and command allowlists."
                if is_docker else
                "Local-jail sandbox: cwd/env/time/output limits and a command allowlist, but not a container. "
                "Do not import untrusted repositories whose tests you would not run yourself.")
        return {**c.router.describe(), "sandbox_mode": mode,
                "sandbox_note": note,
                "github_token_configured": bool(d.settings.github_token)}

    @r.get("/eval/results")
    async def eval_results() -> dict[str, Any]:
        p = EVAL_DIR.parent / "results" / "summary.json"
        if not p.exists():
            return {"results": None, "note": "no evaluation results yet; run `python -m app.evalkit` in backend/"}
        return {"results": json.loads(p.read_text()), "markdown_available": (p.parent / "summary.md").exists()}

    # ---------------------------------------------------------------- repositories
    @r.post("/repositories", status_code=201)
    async def create_repo(body: RepoCreate) -> dict[str, Any]:
        try:
            row = await import_repo(d, body.source_type, body.source_ref, body.name, body.branch, body.github_token)
        except RepoError as e:
            raise err(400, "REPO_IMPORT_FAILED", str(e)) from None
        return public_repo(row)

    @r.post("/repositories/upload", status_code=201)
    async def upload_repo(
        files: list[UploadFile] = File(...),
        name: str | None = Form(None),
    ) -> dict[str, Any]:
        if not files:
            raise err(400, "NO_FILES", "No files uploaded")

        uid = new_id("upl")[-8:].lower()
        repo_name = (name or "").strip()

        # Check if single zip file
        if len(files) == 1 and files[0].filename and files[0].filename.endswith(".zip"):
            zf_bytes = await files[0].read()
            import io
            import zipfile
            try:
                zf = zipfile.ZipFile(io.BytesIO(zf_bytes))
            except Exception as e:
                raise err(400, "INVALID_ZIP", f"Uploaded file is not a valid zip archive: {e}") from None

            dest = d.settings.repos_dir / f"upload_{uid}"
            dest.mkdir(parents=True, exist_ok=True)
            for member in zf.infolist():
                if member.is_dir():
                    continue
                p = Path(member.filename)
                if p.is_absolute() or ".." in p.parts:
                    continue
                target = (dest / p).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
            if not repo_name and files[0].filename:
                repo_name = Path(files[0].filename).stem
        else:
            dest = d.settings.repos_dir / f"upload_{uid}"
            dest.mkdir(parents=True, exist_ok=True)
            for f in files:
                fn = f.filename or "file"
                p = Path(fn)
                if p.is_absolute() or ".." in p.parts:
                    continue
                target = (dest / p).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                content = await f.read()
                target.write_bytes(content)
            if not repo_name and files[0].filename:
                first_part = Path(files[0].filename).parts[0]
                if first_part and first_part != ".":
                    repo_name = first_part

        # If all uploaded files are inside a single top-level directory, move them up
        subdirs = [p for p in dest.iterdir() if p.name != ".git"]
        if len(subdirs) == 1 and subdirs[0].is_dir():
            single_child = subdirs[0]
            if not repo_name:
                repo_name = single_child.name
            for item in list(single_child.iterdir()):
                shutil.move(str(item), str(dest / item.name))
            shutil.rmtree(single_child, ignore_errors=True)

        if not (dest / ".git").is_dir():
            try:
                await git(dest, "init", "-q")
                await git(dest, "config", "user.email", "devpilot@pecathon.internal")
                await git(dest, "config", "user.name", "DevPilot")
                await git(dest, "add", "-A")
                await git(dest, "commit", "-q", "-m", "Initial commit from uploaded folder", "--allow-empty")
            except Exception:
                pass

        try:
            row = await import_repo(d, "LOCAL_PATH", str(dest), name=repo_name or f"upload-{uid}")
        except RepoError as e:
            shutil.rmtree(dest, ignore_errors=True)
            raise err(400, "REPO_IMPORT_FAILED", str(e)) from None

        return public_repo(row)

    @r.get("/repositories")
    async def list_repos() -> dict[str, Any]:
        return {"repositories": [public_repo(x) for x in d.db.select(repositories, order_by="created_at", desc=True)]}

    @r.get("/repositories/parse")
    async def parse_url(url: str) -> dict[str, Any]:
        p = parse_github_url(url)
        return {"valid": bool(p), "owner": p[0] if p else None, "name": p[1] if p else None}

    # ---------------------------------------------------------------- demo scenarios (scripted model; clearly labelled)
    @r.get("/demo/scenarios")
    async def demo_scenarios() -> dict[str, Any]:
        out = []
        for p in sorted(EVAL_DIR.glob("*/mission.json")):
            j = json.loads(p.read_text())
            out.append({k: j.get(k) for k in ("id", "title", "prompt", "category", "description")} | {"scripted": (p.parent / "script.json").exists()})
        return {"scenarios": out, "note": "Demo missions replay a scripted model; tools, tests, verifier and gate are real."}

    @r.post("/demo/missions", status_code=201)
    async def demo_mission(body: DemoCreate) -> dict[str, Any]:
        base = EVAL_DIR / body.scenario_id
        if not (base / "mission.json").exists() or ".." in body.scenario_id:
            raise err(404, "NOT_FOUND", "unknown scenario")
        meta = json.loads((base / "mission.json").read_text())
        dest = d.settings.data_dir / "demo" / f"{body.scenario_id}-{new_id('d')[-6:].lower()}"
        shutil.copytree(base / "repo", dest)
        row = await import_repo(d, "LOCAL_PATH", str(dest), name=f"demo: {body.scenario_id}")
        m = st.create_mission(row["id"], meta["title"], meta["prompt"], meta.get("config", {}), "scripted")
        c.router.register_script(m["id"], json.loads((base / "script.json").read_text()))
        if body.start:
            c.runner.start(m["id"])
        return mission_detail(m["id"])

    # ---------------------------------------------------------------- missions
    @r.post("/missions", status_code=201)
    async def create_mission(body: MissionCreate) -> dict[str, Any]:
        if not d.db.get(repositories, body.repository_id):
            raise err(404, "NOT_FOUND", "repository not found")
        if not c.router.live_providers():
            raise err(409, "NO_MODEL_PROVIDER", "No model provider is configured. Set ANTHROPIC_API_KEY + ANTHROPIC_MODEL or OPENAI_API_KEY + OPENAI_MODEL, "
                                                "or run a demo scenario (scripted model).")
        m = st.create_mission(body.repository_id, body.title, body.prompt, body.config, "live")
        if body.start:
            c.runner.start(m["id"])
        return mission_detail(m["id"])

    @r.get("/missions")
    async def list_missions(status: str | None = None, repository_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        rows = d.db.select(missions, order_by="created_at", desc=True, limit=min(limit, 500))
        wanted = set(status.split(",")) if status else None
        out = []
        for m in rows:
            if wanted and m["status"] not in wanted or (repository_id and m["repository_id"] != repository_id):
                continue
            repo = d.db.get(repositories, m["repository_id"])
            out.append({"id": m["id"], "title": m["title"], "status": m["status"], "status_reason": m["status_reason"], "mode": m["mode"],
                        "repository": {"id": m["repository_id"], "name": repo["name"] if repo else None, "source_type": repo["source_type"] if repo else None},
                        "counters": {"steps": m["steps"], "repair_cycles": m["repair_cycles"], "replans": m["replans"]},
                        "tokens_used": m["tokens_used"], "created_at": m["created_at"], "updated_at": m["updated_at"],
                        "pending_action": {"AWAITING_HUMAN": "answer", "AWAITING_APPROVAL": "approval"}.get(m["status"])})
        return {"missions": out}

    def mission_detail(mid: str) -> dict[str, Any]:
        m = get_mission(mid)
        repo = d.db.get(repositories, m["repository_id"])
        execs = d.db.select(agent_executions, order_by="started_at", where_cols={"mission_id": mid})
        agents: dict[str, Any] = {a: {"agent_id": a, "status": "idle", "current_task_id": None, "executions": 0} for a in
                                  ("master", "planner", "developer", "tester", "security", "verifier")}
        for e in execs:
            a = agents.setdefault(e["agent_id"], {"agent_id": e["agent_id"], "status": "idle", "current_task_id": None, "executions": 0})
            a["executions"] += 1
            if e["status"] == "RUNNING":
                a["status"], a["current_task_id"] = "thinking", e["task_id"]
            elif e["status"] == "ERROR":
                a["last_error"] = e["error"]
        if any(x["decision"] for x in [] or []):
            pass
        pend_h = next((q for q in reversed(st.human_requests(mid)) if q["status"] == "OPEN"), None)
        gate = None
        if m["status"] == S.AWAITING_APPROVAL:
            gate = master.gate(master.view(mid)).as_dict()
        lim = {**{"max_tokens": 400_000}, **((m["config"] or {}).get("limits") or {})}
        return {
            "id": m["id"], "title": m["title"], "request": m["request"], "status": m["status"], "status_reason": m["status_reason"], "mode": m["mode"],
            "repository": public_repo(repo) if repo else None, "base_commit": m["base_commit"],
            "objectives": (m["plan_summary"] or {}).get("objectives", []), "risks": (m["plan_summary"] or {}).get("risks", []),
            "acceptance_criteria": [{"id": x["ac_key"], "text": x["text"], "verification_method": x["verification"].get("method"), "verification": x["verification"],
                                     "status": x["status"], "evidence_refs": x["evidence_refs"]} for x in st.criteria(mid)],
            "criteria_version": m["criteria_version"],
            "counters": {"steps": m["steps"], "repair_cycles": m["repair_cycles"], "replans": m["replans"]},
            "budgets": {"tokens": {"limit": lim["max_tokens"], "used": m["tokens_used"]}},
            "agents": list(agents.values()), "pending_human_request": pend_h, "gate": gate, "current_patch_sha256": m["current_patch_sha256"],
            "state_version": m["state_version"],
            "sandbox_mode": "container_isolated" if (Path("/.dockerenv").exists() or bool(os.environ.get("DOCKER_CONTAINER"))) else "local_jail",
            "outcome": m["outcome"],
            "config": {k: v for k, v in (m["config"] or {}).items() if not k.startswith("_")}, "created_at": m["created_at"], "updated_at": m["updated_at"],
        }

    @r.get("/missions/{mid}")
    async def get_one(mid: str) -> dict[str, Any]:
        return mission_detail(mid)

    @r.post("/missions/{mid}/start")
    async def start(mid: str) -> dict[str, Any]:
        m = get_mission(mid)
        if m["status"] != S.CREATED:
            return mission_detail(mid)
        if m["mode"] == "live" and not c.router.live_providers():
            raise err(409, "NO_MODEL_PROVIDER", "No model provider configured")
        c.runner.start(mid)
        return mission_detail(mid)

    def control(fn: Any, mid: str) -> dict[str, Any]:
        get_mission(mid)
        try:
            fn(mid)
        except IllegalTransition as e:
            raise err(409, "ILLEGAL_TRANSITION", str(e), src=str(e.src), dst=str(e.dst)) from None
        return mission_detail(mid)

    @r.post("/missions/{mid}/pause")
    async def pause(mid: str) -> dict[str, Any]:
        return control(c.runner.pause, mid)

    @r.post("/missions/{mid}/resume")
    async def resume(mid: str) -> dict[str, Any]:
        return control(c.runner.unpause, mid)

    @r.post("/missions/{mid}/cancel")
    async def cancel(mid: str) -> dict[str, Any]:
        return control(c.runner.cancel, mid)

    @r.post("/missions/{mid}/respond")
    async def respond(mid: str, body: RespondReq) -> dict[str, Any]:
        m = get_mission(mid)
        req = d.db.get(human_requests, body.request_id)
        if not req or req["mission_id"] != mid or req["status"] != "OPEN" or m["status"] != S.AWAITING_HUMAN:
            raise err(409, "NO_OPEN_REQUEST", "there is no open question with that id")
        opts = {o["id"] for o in req["options"]}
        opt = body.option or ("answer" if req["kind"] == "CLARIFICATION" else "hint")
        if req["kind"] == "CLARIFICATION" and opt == "answer" and not (body.text or "").strip():
            raise err(422, "TEXT_REQUIRED", "an answer is required")
        if opt not in opts and not opt.startswith("relax:"):
            raise err(422, "BAD_OPTION", f"option must be one of {sorted(opts)}")
        c.runner.resume(mid, {"option": opt, "text": body.text})
        return mission_detail(mid)

    # ---------------------------------------------------------------- read models
    @r.get("/missions/{mid}/tasks")
    async def tasks(mid: str) -> dict[str, Any]:
        get_mission(mid)
        ts, deps_ = st.tasks(mid), st.dependencies(mid)
        by = {t["id"]: t for t in ts}
        return {"tasks": [{"id": t["id"], "key": t["key"], "kind": t["kind"], "title": t["title"], "description": t["description"], "status": t["status"],
                           "assignee": t["assignee_agent"], "retries": t["retries"], "criteria_refs": t["criteria_refs"], "files_hint": t["files_hint"],
                           "depends_on": [b for (a, b) in deps_ if a == t["id"] and b in by], "failure_context": t["failure_context"],
                           "started_at": t["started_at"], "finished_at": t["finished_at"]} for t in ts]}

    @r.get("/missions/{mid}/messages")
    async def messages(mid: str, type: str | None = None, agent: str | None = None, correlation_id: str | None = None) -> dict[str, Any]:
        get_mission(mid)
        rows = st.messages(mid)
        rows = [x for x in rows if (not type or x["type"] == type) and (not agent or agent in (x["sender"], x["recipient"])) and (not correlation_id or x["correlation_id"] == correlation_id)]
        return {"messages": rows}

    @r.get("/missions/{mid}/decisions")
    async def decisions_(mid: str) -> dict[str, Any]:
        get_mission(mid)
        return {"decisions": d.db.select(decisions, order_by="step", where_cols={"mission_id": mid})}

    @r.get("/missions/{mid}/logs")
    async def logs(mid: str, agent: str | None = None, tool: str | None = None, status: str | None = None) -> dict[str, Any]:
        get_mission(mid)
        rows = [x for x in st.tool_calls(mid) if (not agent or x["agent_id"] == agent) and (not tool or x["tool"] == tool) and (not status or x["status"] == status)]
        return {"tool_calls": rows}

    @r.get("/missions/{mid}/tool-calls/{tcl}")
    async def tool_call(mid: str, tcl: str) -> dict[str, Any]:
        get_mission(mid)
        row = d.db.get(tool_calls, tcl)
        if not row or row["mission_id"] != mid:
            raise err(404, "NOT_FOUND", "tool call not found")
        full = None
        if row["output_ref"]:
            ref = Path(row["output_ref"]).resolve()
            if d.settings.artifacts_dir.resolve() in ref.parents and ref.exists():
                full = ref.read_text("utf-8", "replace")
        return {**row, "full_output": full}

    async def ctx_for(mid: str):
        m = get_mission(mid)
        if not m["workspace_path"]:
            return None, m
        return make_ctx(d, m, "system"), m

    @r.get("/missions/{mid}/diffs")
    async def diffs(mid: str) -> dict[str, Any]:
        ctx, m = await ctx_for(mid)
        if ctx is None or not Path(m["workspace_path"]).exists():
            return {"patch_sha256": None, "files": []}
        patch, sha = await compute_patch(ctx)
        files = []
        for f in analyze_patch(patch)["files"]:
            orig = None
            if f["change_type"] != "ADD":
                try:
                    orig = (await git(ctx.workspace, "show", f"{m['base_commit']}:{f['path']}"))[:200_000]
                except GitError:
                    orig = None
            p = ctx.workspace / f["path"]
            mod = p.read_text("utf-8", "replace")[:200_000] if f["change_type"] != "DELETE" and p.is_file() else None
            try:
                unified = (await git(ctx.workspace, "diff", "--cached", "--no-color", m["base_commit"], "--", f["path"]))[:200_000]
            except GitError:
                unified = ""
            files.append({**f, "original": orig, "modified": mod, "unified": unified})
        return {"patch_sha256": sha, "files": files}

    @r.get("/missions/{mid}/patch", response_class=PlainTextResponse)
    async def patch(mid: str) -> str:
        ctx, _ = await ctx_for(mid)
        if ctx is None:
            return ""
        return (await compute_patch(ctx))[0]

    @r.get("/missions/{mid}/test-runs")
    async def test_runs(mid: str) -> dict[str, Any]:
        get_mission(mid)
        return {"runs": st.test_runs(mid)}

    @r.get("/missions/{mid}/findings")
    async def findings(mid: str, status: str | None = None, severity: str | None = None) -> dict[str, Any]:
        get_mission(mid)
        return {"findings": [f for f in st.findings(mid) if (not status or f["status"] == status) and (not severity or f["severity"] == severity)]}

    @r.post("/missions/{mid}/findings/{fid}/waive")
    async def waive(mid: str, fid: str, body: WaiveReq) -> dict[str, Any]:
        get_mission(mid)
        f = next((x for x in st.findings(mid) if x["id"] == fid), None)
        if not f:
            raise err(404, "NOT_FOUND", "finding not found")
        st.set_finding_status(fid, "WAIVED_BY_HUMAN", reason=body.reason, actor="human")
        return {"id": fid, "status": "WAIVED_BY_HUMAN"}

    @r.get("/missions/{mid}/verification")
    async def verification(mid: str) -> dict[str, Any]:
        get_mission(mid)
        return {"verification": st.latest_verification(mid)}

    @r.get("/missions/{mid}/report")
    async def report(mid: str, format: str = "json") -> Any:
        m = get_mission(mid)
        o = m["outcome"] or (reports.build_outcome(d, mid, m["status"], m["status_reason"]) if m["workspace_path"] else None)
        if o is None:
            raise err(404, "NO_REPORT", "no report yet")
        if format == "md":
            return PlainTextResponse(reports.to_markdown(m["title"], o))
        return {"report": o, "final": m["status"] in TERMINAL_STATUSES}

    @r.get("/missions/{mid}/replay")
    async def replay(mid: str) -> dict[str, Any]:
        get_mission(mid)
        return {"events": bus.history(mid)}

    # ---------------------------------------------------------------- approvals
    @r.post("/missions/{mid}/approvals")
    async def approve(mid: str, body: ApprovalReq) -> dict[str, Any]:
        m = get_mission(mid)
        if m["status"] != S.AWAITING_APPROVAL:
            raise err(409, "NOT_AWAITING_APPROVAL", f"mission is {m['status']}")
        if body.patch_sha256 != m["current_patch_sha256"]:
            raise err(409, "STALE_PATCH", "the patch changed since you opened it; review it again", current=m["current_patch_sha256"])
        if body.decision == "CHANGES_REQUESTED" and not (body.comment or "").strip():
            raise err(422, "COMMENT_REQUIRED", "describe the changes you want")
        if body.decision == "APPROVED":
            g = master.gate(master.view(mid))
            if not g.clear:
                raise err(409, "GATE_NOT_CLEAR", "the completion gate is not clear", reasons=g.reasons)
            missing = set(g.needs_ack) - set(body.acknowledged_criteria)
            if missing:
                raise err(409, "ACK_REQUIRED", "acknowledge the criteria that could not be machine-verified", criteria=sorted(missing))
            if (body.publish.push or body.publish.open_pr):
                repo = d.db.get(repositories, m["repository_id"])
                if not repo or repo["source_type"] != "GIT_URL":
                    raise err(422, "PUBLISH_UNSUPPORTED", "push/PR is only available for repositories imported from a GitHub URL")
                if body.publish.open_pr and not body.publish.push:
                    raise err(422, "PUSH_REQUIRED", "opening a PR requires pushing the branch")
        payload = body.model_dump()
        c.runner.resume(mid, payload)
        return {"status": "accepted", "decision": body.decision}

    @r.post("/missions/{mid}/rollback")
    async def rollback(mid: str) -> dict[str, Any]:
        m = get_mission(mid)
        repo = d.db.get(repositories, m["repository_id"])
        if m["status"] != S.COMPLETED or not repo or repo["source_type"] != "LOCAL_PATH":
            raise err(409, "NOT_ROLLBACKABLE", "only completed missions applied to a local path can be rolled back")
        try:
            return await publish.rollback_local(d, mid, Path(repo["local_path"]))
        except GitError as e:
            raise err(409, "ROLLBACK_FAILED", str(e)[:200]) from None

    # ---------------------------------------------------------------- metrics (real data only)
    @r.get("/missions/{mid}/metrics")
    async def metrics(mid: str) -> dict[str, Any]:
        m = get_mission(mid)
        tcs = st.tool_calls(mid)
        execs = d.db.select(agent_executions, where_cols={"mission_id": mid})
        sigs = Counter((t["task_id"], t["tool"], json.dumps(t["args"], sort_keys=True)) for t in tcs if t["agent_id"] == "developer")
        dev_calls = sum(sigs.values())
        redundant = sum(n - 1 for n in sigs.values())
        runs = [x for x in st.test_runs(mid) if x["kind"] == "TEST"]
        from ...db import model_calls

        mc = d.db.select(model_calls, where_cols={"mission_id": mid})
        per_agent: dict[str, Any] = {}
        for e in execs:
            a = per_agent.setdefault(e["agent_id"], {"executions": 0, "errors": 0})
            a["executions"] += 1
            a["errors"] += e["status"] == "ERROR"
        for x in mc:
            a = per_agent.setdefault(x["purpose"], {"executions": 0, "errors": 0})
            a["tokens_in"] = a.get("tokens_in", 0) + (x["tokens_in"] or 0)
            a["tokens_out"] = a.get("tokens_out", 0) + (x["tokens_out"] or 0)
        return {
            "tokens_used": m["tokens_used"], "model_calls": len(mc), "tool_calls": len(tcs), "tool_denied": sum(t["status"] == "DENIED" for t in tcs),
            "tool_errors": sum(t["status"] == "ERROR" for t in tcs), "developer_tool_calls": dev_calls,
            "redundant_tool_call_rate": (round(redundant / dev_calls, 3) if dev_calls else None), "distinct_developer_tools": len({t["tool"] for t in tcs if t["agent_id"] == "developer"}),
            "repair_cycles": m["repair_cycles"], "replans": m["replans"], "steps": m["steps"], "messages": len(st.messages(mid)),
            "test_runs": len(runs), "final_test_outcome": runs[-1]["outcome"] if runs else None,
            "findings": {"total": len(st.findings(mid)), "open": sum(f["status"] in ("OPEN", "DISPUTED", "FIX_PROPOSED") for f in st.findings(mid))},
            "cost_usd": None, "cost_note": "no per-token prices are configured, so cost is not estimated", "per_agent": per_agent,
        }

    # ---------------------------------------------------------------- SSE
    @r.get("/missions/{mid}/events")
    async def events(mid: str, request: Request, last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), after: str | None = None) -> StreamingResponse:
        get_mission(mid)

        def fmt(e: dict[str, Any]) -> str:
            data = {"mission_id": e["mission_id"], "ts": e["created_at"], "actor": e["actor"], "task_id": e["task_id"], **(e["payload"] or {})}
            return f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(data, default=str)}\n\n"

        async def gen():  # type: ignore[no-untyped-def]
            q = bus.subscribe(mid)
            try:
                last = last_event_id or after
                for e in bus.history(mid, last):
                    last = e["id"]
                    yield fmt(e)
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if last and e["id"] <= last:
                        continue
                    last = e["id"]
                    yield fmt(e)
            finally:
                bus.unsubscribe(mid, q)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return r
