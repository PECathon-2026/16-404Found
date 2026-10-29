"""fs.* tools (T2.07)."""
from __future__ import annotations

import fnmatch
import os
import re

from pydantic import BaseModel, Field

from ..common.detect import SKIP
from ..common.tamper import is_test_path
from ..sandbox.pathjail import PathViolation, resolve_in
from .base import ToolContext, ToolError, ToolSpec
from .ws import exists_at_base, record_change

PROTECTED = [".env", ".env.*", "*.pem", "id_rsa*", "id_ed25519*", "*.key"]


def _jail(ctx: ToolContext, p: str, write: bool = False):
    try:
        return resolve_in(ctx.workspace, p, for_write=write)
    except PathViolation as e:
        raise ToolError("POLICY_DENIED", str(e)) from None


def _protected(path: str) -> bool:
    name = os.path.basename(path)
    return any(fnmatch.fnmatch(name, pat) for pat in PROTECTED) or path.startswith(".github/workflows/")


async def _write_policy(ctx: ToolContext, path: str, creating: bool) -> None:
    if _protected(path):
        raise ToolError("POLICY_DENIED", f"{path} is a protected path")
    if ctx.agent_id == "tester" and not is_test_path(path):
        raise ToolError("POLICY_DENIED", "the tester may only change test files")
    if is_test_path(path) and not creating and await exists_at_base(ctx, path) and ctx.task_kind != "WRITE_TESTS":
        raise ToolError("POLICY_DENIED", f"{path} is an existing test file; existing tests are protected outside WRITE_TESTS tasks "
                                         "(fix the implementation, or send a REPLAN_REQUEST explaining why the test is wrong)")


class ReadArgs(BaseModel):
    path: str
    start_line: int = Field(1, ge=1)
    end_line: int | None = None


async def fs_read(ctx: ToolContext, a: ReadArgs) -> dict:
    p = _jail(ctx, a.path)
    if not p.is_file():
        raise ToolError("NOT_FOUND", f"{a.path} is not a file")
    raw = p.read_bytes()
    if b"\x00" in raw[:2048]:
        raise ToolError("INVALID_ARGS", "binary files cannot be read")
    lines = raw.decode("utf-8", "replace").splitlines()
    end = min(a.end_line or a.start_line + 399, a.start_line + 399, len(lines))
    chunk = lines[a.start_line - 1:end]
    return {"path": a.path, "start_line": a.start_line, "end_line": end, "total_lines": len(lines),
            "truncated": end < len(lines), "content": "\n".join(f"{a.start_line + i}\t{ln}" for i, ln in enumerate(chunk))}


class ListArgs(BaseModel):
    path: str = "."
    depth: int = Field(1, ge=1, le=4)


async def fs_list(ctx: ToolContext, a: ListArgs) -> dict:
    root = _jail(ctx, a.path)
    if not root.is_dir():
        raise ToolError("NOT_FOUND", f"{a.path} is not a directory")
    out = []
    base_depth = len(root.relative_to(ctx.workspace).parts)
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        depth = len(os.path.relpath(cur, root).split(os.sep)) if cur != str(root) else 0
        if depth >= a.depth:
            dirs[:] = []
        for n in sorted(files):
            out.append(os.path.relpath(os.path.join(cur, n), ctx.workspace))
        for d in dirs:
            out.append(os.path.relpath(os.path.join(cur, d), ctx.workspace) + "/")
        if len(out) > 400:
            break
    _ = base_depth
    return {"entries": out[:400], "truncated": len(out) > 400}


class SearchArgs(BaseModel):
    pattern: str
    path: str = "."
    regex: bool = True
    glob: str | None = None
    max_results: int = Field(50, ge=1, le=200)


async def fs_search(ctx: ToolContext, a: SearchArgs) -> dict:
    root = _jail(ctx, a.path)
    try:
        rx = re.compile(a.pattern if a.regex else re.escape(a.pattern))
    except re.error as e:
        raise ToolError("INVALID_ARGS", f"bad regex: {e}") from None
    matches = []
    files = [root] if root.is_file() else (p for p in sorted(root.rglob("*")))
    for p in files:
        rel = p.relative_to(ctx.workspace)
        if any(part in SKIP for part in rel.parts) or not p.is_file() or p.is_symlink():
            continue
        if a.glob and not fnmatch.fnmatch(p.name, a.glob):
            continue
        try:
            text = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append({"path": str(rel), "line": i, "text": line.strip()[:200]})
                if len(matches) >= a.max_results:
                    return {"matches": matches, "truncated": True}
    return {"matches": matches, "truncated": False}


class Edit(BaseModel):
    old: str
    new: str
    replace_all: bool = False


class EditArgs(BaseModel):
    path: str
    edits: list[Edit] = Field(min_length=1)


async def fs_edit(ctx: ToolContext, a: EditArgs) -> dict:
    p = _jail(ctx, a.path, write=True)
    if not p.is_file():
        raise ToolError("NOT_FOUND", f"{a.path} does not exist (use fs.create for new files)")
    await _write_policy(ctx, a.path, creating=False)
    text = p.read_text("utf-8")
    for i, e in enumerate(a.edits):
        n = text.count(e.old)
        if n == 0:
            raise ToolError("CONFLICT", f"edit {i}: `old` text not found; re-read the file and retry")
        if n > 1 and not e.replace_all:
            raise ToolError("CONFLICT", f"edit {i}: `old` text matches {n} places; add context or set replace_all")
        text = text.replace(e.old, e.new) if e.replace_all else text.replace(e.old, e.new, 1)
    p.write_text(text, "utf-8")
    return {"path": a.path, "edits_applied": len(a.edits), **await record_change(ctx, a.path, "MODIFY")}


class CreateArgs(BaseModel):
    path: str
    content: str
    overwrite: bool = False


async def fs_create(ctx: ToolContext, a: CreateArgs) -> dict:
    p = _jail(ctx, a.path, write=True)
    if p.exists() and not a.overwrite:
        raise ToolError("CONFLICT", f"{a.path} already exists; use fs.edit or set overwrite=true")
    await _write_policy(ctx, a.path, creating=not p.exists())
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(a.content, "utf-8")
    return {"path": a.path, "bytes": len(a.content), **await record_change(ctx, a.path, "MODIFY" if existed else "ADD")}


class DeleteArgs(BaseModel):
    path: str


async def fs_delete(ctx: ToolContext, a: DeleteArgs) -> dict:
    p = _jail(ctx, a.path, write=True)
    if not p.is_file():
        raise ToolError("NOT_FOUND", f"{a.path} is not a file")
    if is_test_path(a.path):
        raise ToolError("POLICY_DENIED", "test files cannot be deleted")
    if _protected(a.path):
        raise ToolError("POLICY_DENIED", f"{a.path} is a protected path")
    p.unlink()
    return {"path": a.path, **await record_change(ctx, a.path, "DELETE")}


SPECS = [
    ToolSpec("fs.read", "Read a file (max 400 lines per call, numbered). Use start_line/end_line to page.", ReadArgs, fs_read),
    ToolSpec("fs.list", "List files/directories under a path (ignores .git, node_modules, caches).", ListArgs, fs_list),
    ToolSpec("fs.search", "Search file contents with a regex (or literal) across the workspace.", SearchArgs, fs_search),
    ToolSpec("fs.edit", "Edit an existing file by exact text replacement. `old` must match exactly once unless replace_all.", EditArgs, fs_edit, "workspace_write"),
    ToolSpec("fs.create", "Create a new file (refuses to overwrite unless overwrite=true).", CreateArgs, fs_create, "workspace_write"),
    ToolSpec("fs.delete", "Delete a tracked non-test file.", DeleteArgs, fs_delete, "workspace_write"),
]
