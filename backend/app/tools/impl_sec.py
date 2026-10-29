"""sec.* tools (T2.11)."""
from __future__ import annotations

from pydantic import BaseModel

from ..common import scanners
from ..sandbox.git import git
from .base import ToolContext, ToolError, ToolSpec
from .ws import compute_patch


class ScanArgs(BaseModel):
    paths: list[str] | None = None


async def _changed(ctx: ToolContext) -> set[str]:
    from ..common.tamper import analyze_patch

    patch, _ = await compute_patch(ctx)
    return {f["path"] for f in analyze_patch(patch)["files"]}


def _tag(items: list[dict], changed: set[str]) -> list[dict]:
    for it in items:
        it["scope"] = "changed" if it["file"] in changed else "pre_existing"
    return items


async def scan_secrets(ctx: ToolContext, a: ScanArgs) -> dict:
    changed = await _changed(ctx)
    items = _tag(scanners.scan_secrets(ctx.workspace, a.paths), changed)
    return {"findings": items, "scanned": "paths" if a.paths else "workspace"}


async def scan_patterns(ctx: ToolContext, a: ScanArgs) -> dict:
    changed = await _changed(ctx)
    items = _tag(scanners.scan_patterns(ctx.workspace, a.paths), changed)
    inj = _tag(scanners.scan_injection(ctx.workspace), changed) if not a.paths else []
    return {"findings": items + inj, "scanned": "paths" if a.paths else "workspace"}


async def review_quality(ctx: ToolContext, a: "NoArgs") -> dict:
    patch, _ = await compute_patch(ctx)
    from ..common.detect import detect

    ll = detect(ctx.workspace)["conventions"].get("line_length")
    return {"findings": scanners.quality_review(patch, ll)}


class NoArgs(BaseModel):
    pass


async def audit_deps(ctx: ToolContext, a: NoArgs) -> dict:
    # No offline advisory database is bundled and the sandbox has no network: report the gap, never "clean".
    raise ToolError("ENV_MISSING_TOOL", "dependency audit unavailable: no advisory database reachable from the sandbox",
                    alternatives=["enable permissions.network with an allowlisted proxy (not implemented)"])


_ = git
SPECS = [
    ToolSpec("sec.review_quality", "Deterministic code-review heuristics on the patch (readability, consistency, test coverage).", NoArgs, review_quality),
    ToolSpec("sec.scan_secrets", "Scan for hard-coded secrets (values are masked).", ScanArgs, scan_secrets),
    ToolSpec("sec.scan_patterns", "Scan source for injection/unsafe-operation patterns and prompt-injection text.", ScanArgs, scan_patterns),
    ToolSpec("sec.audit_deps", "Dependency vulnerability audit (reports unavailable when no advisory source exists).", NoArgs, audit_deps),
]
