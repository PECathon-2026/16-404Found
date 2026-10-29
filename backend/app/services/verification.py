"""Launch the verifier process and persist its report. The verifier never sees agent output."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ..common.ids import new_id, now_iso
from ..db import verification_reports
from ..deps import Deps
from ..tools.base import ToolContext
from ..tools.ws import compute_patch

VERIFY_TIMEOUT_S = 420


async def run_verification(deps: Deps, ctx: ToolContext) -> dict[str, Any]:
    s = deps.state
    m = s.mission(ctx.mission_id)
    patch, sha = await compute_patch(ctx)
    art = deps.settings.artifacts_dir / ctx.mission_id / "verify"
    art.mkdir(parents=True, exist_ok=True)
    patch_file = art / "candidate.patch"
    patch_file.write_text(patch)
    criteria = [{"id": c["ac_key"], "text": c["text"], "verification": c["verification"]} for c in s.criteria(ctx.mission_id)]
    spec = {"workspace_git_dir": str(ctx.workspace), "base_commit": m["base_commit"], "patch_file": str(patch_file), "patch_sha256": sha,
            "criteria_version": m["criteria_version"], "criteria": criteria, "scratch": str(art / "scratch")}
    spec_path, report_path = art / "spec.json", art / "report.json"
    spec_path.write_text(json.dumps(spec))
    report_path.unlink(missing_ok=True)
    ver_id = new_id("ver")
    started = now_iso()
    deps.bus.publish(ctx.mission_id, "verification.started", "verifier", {"verification_id": ver_id, "patch_sha256": sha})
    backend_dir = Path(__file__).resolve().parents[2]
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "PYTHONPATH": str(backend_dir), "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(art)}
    try:
        proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.verifier", str(spec_path), str(report_path), cwd=str(backend_dir), env=env,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=VERIFY_TIMEOUT_S)
        if proc.returncode != 0 or not report_path.exists():
            raise RuntimeError(f"verifier exited {proc.returncode}: {err.decode()[-300:]}")
        report = json.loads(report_path.read_text())
    except Exception as e:  # noqa: BLE001 - crash/timeout => INCONCLUSIVE, never PASS
        report = {"patch_sha256": sha, "criteria_version": m["criteria_version"], "results": [], "regression_check": {}, "tamper_check": {},
                  "overall": "INCONCLUSIVE", "error": f"verifier failed: {type(e).__name__}: {str(e)[:200]}"}
    deps.db.insert(verification_reports, id=ver_id, mission_id=ctx.mission_id, patch_sha256=sha, criteria_version=m["criteria_version"],
                   overall=report["overall"], results=report["results"], regression_check=report.get("regression_check"),
                   tamper_check=report.get("tamper_check"), started_at=started, ended_at=now_iso())
    for r in report["results"]:
        s.set_criterion_status(ctx.mission_id, r["ac_id"], r["status"], [{"kind": "verification", "id": ver_id, "locator": r["ac_id"]}])
    deps.bus.publish(ctx.mission_id, "verification.completed", "verifier", {
        "verification_id": ver_id, "overall": report["overall"], "patch_sha256": sha, "error": report.get("error"),
        "results_summary": [{"ac_id": r["ac_id"], "status": r["status"], "method": r["method"]} for r in report["results"]],
        "new_failures": (report.get("regression_check") or {}).get("new_failures", [])})
    return {"id": ver_id, **report}
