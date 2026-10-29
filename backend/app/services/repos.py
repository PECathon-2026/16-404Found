"""Repository import: local path or GitHub URL (cloned into a DevPilot-owned directory)."""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ..common.detect import detect
from ..common.ids import new_id, now_iso
from ..db import repositories
from ..deps import Deps
from ..sandbox.git import GitError, git
from .publish import _scrub, auth_env

GITHUB_RE = re.compile(r"^(?:https://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
# Whole subtrees that must never be imported (compared after resolving symlinks: /etc -> /private/etc on macOS).
FORBIDDEN_TREES = ["/etc", "/usr", "/bin", "/sbin", "/System", "/Library", "/dev", "/proc", "/sys", "/boot", "/root", "/lib", "/lib64"]
# Directories that must not be imported *themselves* (their children are normal project folders, e.g. /var/folders/..).
FORBIDDEN_EXACT = ["/", "/var", "/opt", "/private", "/Users", "/home", "/tmp"]


def forbidden_local(p: Path) -> str | None:
    p = p.resolve()
    home = Path.home().resolve()
    if any(p == Path(x).resolve() for x in FORBIDDEN_EXACT) or p == home:
        return "refusing to import a system or home directory; point at a project folder"
    if any(p == (r := Path(t).resolve()) or r in p.parents for t in FORBIDDEN_TREES):
        return "refusing to import a system directory"
    if home in p.parents and p.relative_to(home).parts[0].startswith(".") and p.relative_to(home).parts[0] not in (".config",):
        return "refusing to import a hidden configuration/credentials directory under your home folder"
    return None


class RepoError(Exception):
    pass


def parse_github_url(url: str) -> tuple[str, str] | None:
    m = GITHUB_RE.match(url.strip())
    return (m.group(1), m.group(2)) if m else None


async def import_repo(deps: Deps, source_type: str, source_ref: str, name: str | None = None, branch: str | None = None,
                      token: str | None = None) -> dict[str, Any]:
    rid = new_id("rep")
    s = deps.settings
    if source_type == "LOCAL_PATH":
        p = Path(source_ref).expanduser().resolve()
        if not p.is_dir():
            raise RepoError(f"{source_ref} is not a directory")
        if (why := forbidden_local(p)):
            raise RepoError(why)
        local, owner, gname, url = p, None, None, None
    elif source_type == "GIT_URL":
        gh = parse_github_url(source_ref)
        local_ok = s.allow_local_git_urls and (source_ref.startswith("file://") or Path(source_ref).exists())
        if not gh and not local_ok:
            raise RepoError("only https://github.com/<owner>/<repo> URLs are supported")
        owner, gname = gh if gh else (None, None)
        url = f"https://github.com/{owner}/{gname}.git" if gh else source_ref
        local = s.repos_dir / rid
        local.parent.mkdir(parents=True, exist_ok=True)
        tok = token or (s.github_token or None)
        args = ["clone", "-q", "--depth", "1"] + (["--branch", branch.strip()] if branch and branch.strip() else []) + [url, str(local)]
        try:
            await git(local.parent, *args, env_extra=auth_env(tok) if gh else None, timeout=240)
        except GitError as e:
            shutil.rmtree(local, ignore_errors=True)
            msg = _scrub(str(e), tok)
            # If authentication failed (e.g. invalid token or password manager autofilled a password),
            # retry without authentication in case the repository is public:
            if tok and ("Authentication failed" in msg or "Invalid username or token" in msg or "401" in msg or "403" in msg):
                try:
                    await git(local.parent, *args, env_extra=None, timeout=240)
                    tok = None
                except GitError:
                    pass
            if not local.exists():
                if branch and ("Remote branch" in msg or "not found in upstream" in msg or "Could not find remote branch" in msg):
                    raise RepoError(f"branch '{branch}' does not exist on {owner}/{gname}. (Leave the Branch field blank to use the default branch)") from None
                if re.search(r"not found|Authentication|could not read|403|404", msg, re.I):
                    raise RepoError("could not clone: repository not found, or it is private (if private, provide a GitHub personal access token with repo read scope)") from None
                raise RepoError(f"could not clone: {msg[:200]}") from None
    else:
        raise RepoError("source_type must be LOCAL_PATH or GIT_URL")
    info = detect(local)
    head = None
    default_branch = None
    try:
        head = (await git(local, "rev-parse", "HEAD")).strip()
        default_branch = (await git(local, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    except GitError:
        pass
    row = deps.db.insert(
        repositories, id=rid, name=name or (gname if source_type == "GIT_URL" and gname else local.name), source_type=source_type,
        source_ref=url if source_type == "GIT_URL" else str(local), local_path=str(local), default_branch=default_branch,
        language_hints=info["languages"], head_commit=head, detected_commands=info["detected_commands"], exclusions=[],
        github_owner=owner, github_name=gname, created_at=now_iso())
    return row


async def refresh_clone(deps: Deps, repo: dict[str, Any], token: str | None = None) -> str | None:
    """Best-effort fast-forward of a DevPilot-owned clone before a mission starts. Returns a warning or None."""
    if repo["source_type"] != "GIT_URL":
        return None
    clone = Path(repo["local_path"])
    tok = token or (deps.settings.github_token or None)
    try:
        if (await git(clone, "status", "--porcelain")).strip():
            return "clone has local changes; using it as-is"
        await git(clone, "fetch", "-q", "--depth", "50", "origin", repo["default_branch"] or "HEAD", env_extra=auth_env(tok) if repo["github_owner"] else None, timeout=120)
        await git(clone, "merge", "-q", "--ff-only", "FETCH_HEAD")
    except GitError as e:
        return f"could not refresh from GitHub: {_scrub(str(e), tok)[:160]}"
    return None
