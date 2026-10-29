"""Applying an APPROVED patch (G7) and optional publishing to GitHub. Nothing here runs before human approval,
and push / PR are opt-in per approval (never defaulted)."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import httpx

from ..deps import Deps
from ..sandbox.git import GitError, git

GITHUB_API = "https://api.github.com"


def _scrub(text: str, token: str | None) -> str:
    return text.replace(token, "[REDACTED]") if token else text


def auth_env(token: str | None) -> dict[str, str]:
    """Pass the token via git config env vars (never argv, never the remote URL, never logged)."""
    if not token:
        return {}
    b = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {b}"}


async def _prefix(src: Path) -> tuple[bool, str]:
    try:
        inside = (await git(src, "rev-parse", "--is-inside-work-tree")).strip() == "true"
    except GitError:
        return False, ""
    if not inside:
        return False, ""
    return True, (await git(src, "rev-parse", "--show-prefix")).strip().rstrip("/")


async def apply_to_local(deps: Deps, mid: str, src: Path, patch: str) -> dict[str, Any]:
    run_dir = deps.settings.runs_dir / mid
    run_dir.mkdir(parents=True, exist_ok=True)
    pf = run_dir / "approved.patch"
    pf.write_text(patch)
    is_repo, prefix = await _prefix(src)
    args = ["apply", "--whitespace=nowarn"] + ([f"--directory={prefix}"] if prefix else [])
    await git(src, *args, "--check", str(pf))
    await git(src, *args, str(pf))
    return {"applied_to": str(src), "git_repo": is_repo, "patch_file": str(pf), "rollback": "reverse-apply approved.patch"}


async def rollback_local(deps: Deps, mid: str, src: Path) -> dict[str, Any]:
    pf = deps.settings.runs_dir / mid / "approved.patch"
    if not pf.exists():
        raise GitError("no applied patch recorded for this mission")
    is_repo, prefix = await _prefix(src)
    args = ["apply", "-R", "--whitespace=nowarn"] + ([f"--directory={prefix}"] if prefix else [])
    await git(src, *args, "--check", str(pf))
    await git(src, *args, str(pf))
    return {"rolled_back": True}


def branch_name(mid: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32] or "change"
    return f"devpilot/{slug}-{mid[-6:].lower()}"


async def apply_to_clone(deps: Deps, mid: str, clone: Path, patch: str, title: str, body: str) -> dict[str, Any]:
    """GitHub-sourced repositories: DevPilot owns the clone, so the change lands on a NEW branch, committed locally."""
    if (await git(clone, "status", "--porcelain")).strip():
        raise GitError("the DevPilot-owned clone has uncommitted changes; refusing to apply")
    base_branch = (await git(clone, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    br = branch_name(mid, title)
    await git(clone, "config", "user.email", "devpilot@localhost")
    await git(clone, "config", "user.name", "DevPilot")
    await git(clone, "checkout", "-q", "-b", br)
    pf = deps.settings.runs_dir / mid / "approved.patch"
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(patch)
    await git(clone, "apply", "--whitespace=nowarn", "--check", str(pf))
    await git(clone, "apply", "--whitespace=nowarn", str(pf))
    await git(clone, "add", "-A")
    await git(clone, "commit", "-q", "-m", f"{title}\n\n{body}")
    commit = (await git(clone, "rev-parse", "HEAD")).strip()
    return {"branch": br, "base_branch": base_branch, "commit": commit, "patch_file": str(pf)}


async def push_branch(clone: Path, branch: str, token: str | None, remote: str = "origin") -> dict[str, Any]:
    try:
        await git(clone, "push", "-q", "--set-upstream", remote, branch, env_extra=auth_env(token), timeout=180)
    except GitError as e:
        raise GitError(_scrub(str(e), token)) from None
    return {"pushed": True, "remote": remote, "branch": branch}


async def open_pull_request(owner: str, name: str, token: str, head: str, base: str, title: str, body: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GITHUB_API}/repos/{owner}/{name}/pulls", json={"title": title, "head": head, "base": base, "body": body},
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if r.status_code >= 300:
        raise GitError(f"GitHub PR creation failed (HTTP {r.status_code}): {_scrub(r.text[:200], token)}")
    j = r.json()
    return {"pr_url": j.get("html_url"), "number": j.get("number")}
