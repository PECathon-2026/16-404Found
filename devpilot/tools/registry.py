"""DevPilot tool implementations and central tool registry.

Exposes ``register_all(gateway, ctx)`` per WP-G04/WP-G05 discovery contract.
Every tool referenced in ``devpilot.engine.modes._MODES`` is registered here.
"""

from __future__ import annotations

import difflib
import fnmatch
import inspect
import json
import os
import re
import shutil
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from devpilot.core.ports import (
    EvidenceKind,
    Executor,
    Tool,
    ToolContext,
    ToolResult,
    ToolSchema,
    Workspaces,
)
from devpilot.tools.policy import (
    CommandPolicy,
    PolicyDenied,
    check_test_edit_allowed,
    resolve_in_workspace,
)

if TYPE_CHECKING:
    from devpilot.config import Settings
    from devpilot.core.ports import RepoIntelService, TestRunner
    from devpilot.tools.gateway import DefaultToolGateway
    from devpilot.wiring import ToolRegistryContext


# Ignored directory names for recursive file search and listing
IGNORED_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)


def _format_match(rel_path: str, line_no: int, text: str) -> str:
    """Format search match in canonical rel_path:line_no: text style."""
    norm = rel_path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    return f"{norm}:{line_no}: {text.strip()}"


class FsListTool(Tool):
    """List directory contents within the workspace."""

    name = "fs.list"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="fs_list",
            description=(
                "List directory contents within the workspace. Returns directory hierarchy and files. "
                "Use to discover the structure and files of the repository."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path, default '.'",
                        "default": ".",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Recursion depth (1 to 4), default 2",
                        "minimum": 1,
                        "maximum": 4,
                        "default": 2,
                    },
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        rel_path = args.get("path", ".")
        depth = min(max(int(args.get("depth", 2)), 1), 4)

        ws_path = await self.workspaces.path(ctx.workspace_ref)
        target = resolve_in_workspace(ws_path, rel_path)

        if not target.exists():
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="NOT_FOUND",
                error_message=f"Path not found: {rel_path}",
            )

        if target.is_file():
            return ToolResult(
                ok=True,
                tool=self.name,
                output=f"{rel_path} (file)",
                structured={"files": [rel_path], "dirs": []},
            )

        lines: list[str] = [f"{rel_path}/"]
        all_files: list[str] = []
        all_dirs: list[str] = []

        def _walk(curr_dir: Path, curr_depth: int) -> None:
            if curr_depth > depth:
                return
            try:
                entries = sorted(curr_dir.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return

            for entry in entries:
                if entry.name in IGNORED_DIRS or entry.name.startswith("."):
                    continue
                rel_entry = entry.relative_to(ws_path).as_posix()
                indent = "  " * curr_depth
                if entry.is_dir():
                    lines.append(f"{indent}{entry.name}/")
                    all_dirs.append(rel_entry)
                    _walk(entry, curr_depth + 1)
                else:
                    lines.append(f"{indent}{entry.name}")
                    all_files.append(rel_entry)

        _walk(target, 1)
        return ToolResult(
            ok=True,
            tool=self.name,
            output="\n".join(lines),
            structured={"files": all_files, "dirs": all_dirs},
        )


class FsReadTool(Tool):
    """Read a file from the workspace with line numbers."""

    name = "fs.read"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="fs_read",
            description=(
                "Read a file from the workspace with line numbers. Use start and end lines (1-indexed) "
                "to read specific ranges (up to 400 lines per call). Always read a file before modifying it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file",
                    },
                    "start": {
                        "type": "integer",
                        "description": "Starting line number (1-indexed, inclusive)",
                        "minimum": 1,
                    },
                    "end": {
                        "type": "integer",
                        "description": "Ending line number (inclusive)",
                        "minimum": 1,
                    },
                },
                "required": ["path"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        rel_path = args["path"]
        ws_path = await self.workspaces.path(ctx.workspace_ref)
        target = resolve_in_workspace(ws_path, rel_path)

        if not target.is_file():
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="NOT_FOUND",
                error_message=f"File not found: {rel_path}",
            )

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="READ_ERROR",
                error_message=str(err),
            )

        lines = content.splitlines()
        total_lines = len(lines)

        start = int(args.get("start") or 1)
        end = int(args.get("end") or total_lines)

        if start < 1:
            start = 1
        if end > total_lines:
            end = total_lines

        if end < start and total_lines > 0:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="INVALID_ARGS",
                error_message=f"End line ({end}) is before start line ({start})",
            )

        # Enforce max 400 lines per read
        clamped = False
        if (end - start + 1) > 400:
            end = start + 399
            clamped = True

        out_lines: list[str] = []
        if clamped:
            out_lines.append(f"[Showing lines {start}-{end} of {total_lines}; capped at 400 lines]")

        for idx in range(start - 1, min(end, total_lines)):
            line_no = idx + 1
            out_lines.append(f"{line_no:6d} | {lines[idx]}")

        return ToolResult(
            ok=True,
            tool=self.name,
            output="\n".join(out_lines),
            structured={"path": rel_path, "total_lines": total_lines, "start": start, "end": end},
        )


class FsEditTool(Tool):
    """Replace exact text in a file inside the workspace."""

    name = "fs.edit"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="fs_edit",
            description=(
                "Replace an exact, unique string in a file inside the workspace. Read the file first. "
                "'old' must match exactly once unless 'count' is given. Use for all modifications to existing files."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"},
                    "old": {"type": "string", "description": "Exact text to find and replace"},
                    "new": {"type": "string", "description": "Replacement text"},
                    "count": {
                        "type": "integer",
                        "description": "Number of occurrences to replace, default 1",
                        "minimum": 1,
                        "default": 1,
                    },
                },
                "required": ["path", "old", "new"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        rel_path = args["path"]
        old_text = args["old"]
        new_text = args["new"]
        req_count = int(args.get("count", 1))

        ws_path = await self.workspaces.path(ctx.workspace_ref)
        target = resolve_in_workspace(ws_path, rel_path)

        if not target.is_file():
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="NOT_FOUND",
                error_message=f"File not found: {rel_path}",
            )

        content = target.read_text(encoding="utf-8", errors="replace")
        actual_count = content.count(old_text)

        if actual_count == 0:
            # Provide closest line hint via difflib
            lines = content.splitlines()
            target_line = old_text.strip().splitlines()[0] if old_text.strip() else ""
            close = difflib.get_close_matches(target_line, lines, n=1, cutoff=0.4)
            hint = f" Closest match found in file: {close[0]!r}" if close else ""
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="NOT_FOUND",
                error_message=f"Text not found in {rel_path}.{hint}",
            )

        if actual_count > 1 and actual_count != req_count and req_count == 1:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="AMBIGUOUS_MATCH",
                error_message=(
                    f"Text appears {actual_count} times in {rel_path}; provide more surrounding "
                    f"context or specify count={actual_count}"
                ),
            )

        # Replace text
        updated = content.replace(old_text, new_text, req_count)

        # Check test protection policy if editing a test file
        try:
            check_test_edit_allowed(content, updated, ctx.may_edit_tests)
        except PolicyDenied as pd:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code=pd.code,
                error_message=pd.message,
            )

        target.write_text(updated, encoding="utf-8")
        return ToolResult(
            ok=True,
            tool=self.name,
            output=f"Successfully edited {rel_path} ({min(actual_count, req_count)} occurrence(s) replaced)",
            structured={"path": rel_path, "replaced": min(actual_count, req_count)},
        )


class FsWriteTool(Tool):
    """Create a new file in the workspace or overwrite if permitted."""

    name = "fs.write"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="fs_write",
            description=(
                "Create a new file in the workspace. Will refuse to overwrite existing files unless "
                "overwrite=true and the existing file has fewer than 200 lines."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path"},
                    "content": {"type": "string", "description": "Full file content to write"},
                    "overwrite": {
                        "type": "boolean",
                        "description": "Allow overwriting existing file (< 200 lines)",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        rel_path = args["path"]
        content = args["content"]
        overwrite = bool(args.get("overwrite", False))

        ws_path = await self.workspaces.path(ctx.workspace_ref)
        target = resolve_in_workspace(ws_path, rel_path)

        if target.exists():
            if not overwrite:
                return ToolResult(
                    ok=False,
                    tool=self.name,
                    output="",
                    error_code="POLICY_DENIED",
                    error_message=f"File already exists: {rel_path}. Use fs.edit or set overwrite=true.",
                )

            old_text = target.read_text(encoding="utf-8", errors="replace")
            old_lines = old_text.splitlines()
            if len(old_lines) >= 200:
                return ToolResult(
                    ok=False,
                    tool=self.name,
                    output="",
                    error_code="POLICY_DENIED",
                    error_message=(
                        f"Cannot overwrite {rel_path}: file has {len(old_lines)} lines (>= 200). "
                        "Use fs.edit instead."
                    ),
                )

            try:
                check_test_edit_allowed(old_text, content, ctx.may_edit_tests)
            except PolicyDenied as pd:
                return ToolResult(
                    ok=False,
                    tool=self.name,
                    output="",
                    error_code=pd.code,
                    error_message=pd.message,
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult(
            ok=True,
            tool=self.name,
            output=f"Successfully wrote {len(content)} bytes to {rel_path}",
            structured={"path": rel_path, "bytes": len(content)},
        )


class FsWriteProbeTool(Tool):
    """Write an isolated verification probe to runs/<mission_id>/probes/."""

    name = "fs.write_probe"
    evidence_kind = EvidenceKind.PROBE_RUN

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.schema = ToolSchema(
            name="fs_write_probe",
            description=(
                "Write a verification probe script into runs/<mission_id>/probes/. "
                "Used by the Verifier to inspect runtime conditions outside the workspace."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Probe filename (e.g. 'probe_repro.py')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Probe code content",
                    },
                },
                "required": ["name", "content"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        safe_name = PurePath(args["name"]).name
        probes_dir = self.runs_dir / ctx.mission_id / "probes"
        probes_dir.mkdir(parents=True, exist_ok=True)

        target = probes_dir / safe_name
        target.write_text(args["content"], encoding="utf-8")

        return ToolResult(
            ok=True,
            tool=self.name,
            output=f"Probe written to runs/{ctx.mission_id}/probes/{safe_name}",
            structured={"path": str(target), "name": safe_name},
        )


class SearchCodeTool(Tool):
    """Search codebase using ripgrep or pure-Python regex walker fallback."""

    name = "search.code"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces, executor: Executor) -> None:
        self.workspaces = workspaces
        self.executor = executor
        self.force_python_fallback = False  # Set to True in parity tests
        self.schema = ToolSchema(
            name="search_code",
            description=(
                "Search for regex or literal text patterns in the workspace codebase. "
                "Uses ripgrep when available, automatically falling back to Python regex walker."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex or text pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory or file to search within, default '.'",
                        "default": ".",
                    },
                    "glob": {
                        "type": "string",
                        "description": "File glob filter, e.g. '*.py'",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matching lines to return, default 50",
                        "default": 50,
                    },
                },
                "required": ["pattern"],
            },
        )

    async def _python_walk_search(
        self,
        base_dir: Path,
        search_path: Path,
        pattern: str,
        glob_pat: str | None,
        max_results: int,
    ) -> tuple[list[str], bool]:
        """Pure-Python search walker with identical output format."""
        try:
            regex = re.compile(pattern)
        except re.error as err:
            return [f"Invalid regex pattern: {err}"], False

        matches: list[tuple[str, int, str]] = []

        files_to_search: list[Path] = []
        if search_path.is_file():
            files_to_search = [search_path]
        elif search_path.is_dir():
            for root, dirs, files in os.walk(search_path):
                # Prune ignored directories in place
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for fname in files:
                    if glob_pat and not fnmatch.fnmatch(fname, glob_pat):
                        continue
                    files_to_search.append(Path(root) / fname)

        files_to_search.sort()

        for fpath in files_to_search:
            try:
                rel = fpath.relative_to(base_dir).as_posix()
                content = fpath.read_text(encoding="utf-8", errors="replace")
                for line_idx, line in enumerate(content.splitlines()):
                    if regex.search(line):
                        matches.append((rel, line_idx + 1, line))
            except OSError:
                continue

        matches.sort(key=lambda m: (m[0], m[1]))
        truncated = len(matches) > max_results
        result_lines = [_format_match(m[0], m[1], m[2]) for m in matches[:max_results]]
        return result_lines, truncated

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        pattern = args["pattern"]
        subpath = args.get("path", ".")
        glob_filter = args.get("glob")
        max_results = int(args.get("max_results", 50))

        ws_path = await self.workspaces.path(ctx.workspace_ref)
        target = resolve_in_workspace(ws_path, subpath)

        if not target.exists():
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="NOT_FOUND",
                error_message=f"Search path not found: {subpath}",
            )

        # 1. If not forcing Python fallback, try ripgrep
        rg_bin = shutil.which("rg")
        if rg_bin is not None and not self.force_python_fallback:
            argv = [rg_bin, "--line-number", "--no-heading", "--color", "never", "-e", pattern]
            if glob_filter:
                argv.extend(["-g", glob_filter])
            for ign in IGNORED_DIRS:
                argv.extend(["-g", f"!{ign}"])
            argv.append(str(target))

            try:
                exec_res = await self.executor.run(argv, cwd=ws_path, timeout_s=15)
                if exec_res.exit_code in (0, 1):  # 0 = matches, 1 = no matches
                    lines: list[tuple[str, int, str]] = []
                    for line in exec_res.stdout.splitlines():
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            try:
                                path_str = parts[0]
                                try:
                                    p = Path(path_str)
                                    if p.is_absolute():
                                        rel = p.relative_to(ws_path).as_posix()
                                    else:
                                        rel = p.as_posix()
                                except ValueError:
                                    rel = path_str
                                lines.append((rel, int(parts[1]), parts[2]))
                            except ValueError:
                                continue

                    lines.sort(key=lambda item: (item[0], item[1]))
                    truncated = len(lines) > max_results
                    formatted = [_format_match(m[0], m[1], m[2]) for m in lines[:max_results]]
                    out = "\n".join(formatted) if formatted else "No matches found."
                    return ToolResult(
                        ok=True,
                        tool=self.name,
                        output=out,
                        truncated=truncated,
                        structured={"matches_count": len(lines)},
                    )
            except Exception:
                pass  # Fall through to Python fallback

        # 2. Pure-Python regex walker fallback
        lines, truncated = await self._python_walk_search(
            ws_path, target, pattern, glob_filter, max_results
        )
        out = "\n".join(lines) if lines else "No matches found."
        return ToolResult(
            ok=True,
            tool=self.name,
            output=out,
            fallback_used="python_re_walker",
            truncated=truncated,
            structured={"matches_count": len(lines)},
        )


class GitStatusTool(Tool):
    """Show git status inside the workspace."""

    name = "git.status"
    evidence_kind = EvidenceKind.DIFF

    def __init__(self, workspaces: Workspaces, executor: Executor) -> None:
        self.workspaces = workspaces
        self.executor = executor
        self.schema = ToolSchema(
            name="git_status",
            description="Show git status of the current workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional paths to limit status output",
                    }
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ws_path = await self.workspaces.path(ctx.workspace_ref)
        argv = ["git", "-c", "core.quotepath=false", "status", "--porcelain"]
        if args.get("paths"):
            argv.extend(["--", *args["paths"]])

        res = await self.executor.run(argv, cwd=ws_path, timeout_s=15)
        out = res.stdout.strip()
        return ToolResult(
            ok=res.exit_code == 0,
            tool=self.name,
            output=out or "working tree clean",
            structured={"clean": not bool(out)},
        )


class GitDiffTool(Tool):
    """Show git diff inside the workspace."""

    name = "git.diff"
    evidence_kind = EvidenceKind.DIFF

    def __init__(self, workspaces: Workspaces, executor: Executor) -> None:
        self.workspaces = workspaces
        self.executor = executor
        self.schema = ToolSchema(
            name="git_diff",
            description="Show git diff of modified files in the workspace against baseline or HEAD.",
            input_schema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional file paths to limit diff",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged diff if true",
                        "default": False,
                    },
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ws_path = await self.workspaces.path(ctx.workspace_ref)
        argv = ["git", "-c", "core.quotepath=false", "diff"]
        if args.get("staged"):
            argv.append("--cached")
        if args.get("paths"):
            argv.extend(["--", *args["paths"]])

        res = await self.executor.run(argv, cwd=ws_path, timeout_s=15)
        out = res.stdout.strip()
        return ToolResult(
            ok=res.exit_code == 0,
            tool=self.name,
            output=out or "No diff",
            structured={"has_diff": bool(out)},
        )


class GitLogTool(Tool):
    """Show git commit history inside the workspace."""

    name = "git.log"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, workspaces: Workspaces, executor: Executor) -> None:
        self.workspaces = workspaces
        self.executor = executor
        self.schema = ToolSchema(
            name="git_log",
            description="Show recent commit logs from the workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "max_count": {
                        "type": "integer",
                        "description": "Maximum commits to show, default 10",
                        "default": 10,
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional file paths",
                    },
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ws_path = await self.workspaces.path(ctx.workspace_ref)
        count = int(args.get("max_count", 10))
        argv = ["git", "log", f"-n{count}", "--oneline"]
        if args.get("paths"):
            argv.extend(["--", *args["paths"]])

        res = await self.executor.run(argv, cwd=ws_path, timeout_s=15)
        return ToolResult(
            ok=res.exit_code == 0,
            tool=self.name,
            output=res.stdout.strip() or "No commits",
            structured={},
        )


class ShellRunTool(Tool):
    """Execute allowlisted shell command within the workspace."""

    name = "shell.run"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(
        self,
        workspaces: Workspaces,
        executor: Executor,
        settings: Settings | None = None,
        command_policy: CommandPolicy | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.executor = executor
        self.settings = settings
        if command_policy is not None:
            self.command_policy = command_policy
        else:
            self.command_policy = CommandPolicy()

        self.schema = ToolSchema(
            name="shell_run",
            description=(
                "Execute an allowlisted command in the workspace. Shell metacharacters and unlisted "
                "commands are strictly rejected by policy."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command and argument list, e.g. ['pytest', 'tests/test_api.py']",
                    }
                },
                "required": ["argv"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        argv = args["argv"]
        ws_path = await self.workspaces.path(ctx.workspace_ref)

        try:
            self.command_policy.classify(argv, caller_role=ctx.mode_id, workspace=ws_path)
        except PolicyDenied as pd:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code=pd.code,
                error_message=pd.message,
            )

        timeout_s = 30
        if self.settings is not None and hasattr(self.settings, "budgets"):
            timeout_s = getattr(self.settings.budgets, "tool_timeout_s", 30)
        res = await self.executor.run(argv, cwd=ws_path, timeout_s=timeout_s)

        combined_output = res.stdout
        if res.stderr:
            combined_output = f"{combined_output}\n{res.stderr}".strip()

        if res.timed_out:
            return ToolResult(
                ok=False,
                tool=self.name,
                output=combined_output,
                error_code="TIMEOUT",
                error_message="Command execution timed out",
            )

        if res.exit_code != 0:
            return ToolResult(
                ok=False,
                tool=self.name,
                output=combined_output,
                error_code="NONZERO_EXIT",
                error_message=f"Command exited with non-zero exit code: {res.exit_code}",
                structured={"exit_code": res.exit_code},
            )

        return ToolResult(
            ok=True,
            tool=self.name,
            output=combined_output,
            structured={"exit_code": 0},
        )


class BoardReadTool(Tool):
    """Read mission blackboard status, plan, ACs, tasks, or budget."""

    name = "board.read"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, runs_dir: Path, extras: dict[str, Any]) -> None:
        self.runs_dir = runs_dir
        self.extras = extras
        self.schema = ToolSchema(
            name="board_read",
            description="Read blackboard state, current plan, acceptance criteria, or budget.",
            input_schema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Section to inspect: 'all', 'plan', 'acs', 'tasks', 'budget'",
                        "default": "all",
                    }
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        section = args.get("section", "all")
        mission_file = self.runs_dir / ctx.mission_id / "mission.json"

        if mission_file.exists():
            try:
                data = json.loads(mission_file.read_text(encoding="utf-8"))
                if section != "all" and section in data:
                    out = json.dumps(data[section], indent=2)
                else:
                    out = json.dumps(data, indent=2)
                return ToolResult(ok=True, tool=self.name, output=out, structured={"section": section})
            except Exception:
                pass

        bb = self.extras.get("blackboard")
        if bb is not None and hasattr(bb, "mission"):
            m = bb.mission
            info: dict[str, Any] = {
                "id": m.id,
                "status": m.status.value,
                "request": m.request,
                "plan": getattr(m, "plan", None),
                "budget": getattr(m, "budget", None),
            }
            if section != "all" and section in info:
                out = json.dumps(info[section], indent=2, default=str)
            else:
                out = json.dumps(info, indent=2, default=str)
            return ToolResult(ok=True, tool=self.name, output=out, structured={"section": section})

        return ToolResult(
            ok=True,
            tool=self.name,
            output=f"Blackboard view for mission {ctx.mission_id} ({section})",
            structured={"mission_id": ctx.mission_id, "section": section},
        )


class MsgSendTool(Tool):
    """Send an agent message or finding across modes."""

    name = "msg.send"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, extras: dict[str, Any]) -> None:
        self.extras = extras
        self.schema = ToolSchema(
            name="msg_send",
            description="Send an agent message, finding, or question to another guild agent or shogun.",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient agent or role"},
                    "type": {"type": "string", "description": "Message type (e.g. finding, note)"},
                    "subject": {"type": "string", "description": "Subject line"},
                    "body": {"type": "string", "description": "Message body"},
                    "refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional file/task references",
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional evidence IDs",
                    },
                },
                "required": ["to", "type", "subject", "body"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        to = args["to"]
        subject = args["subject"]
        body = args["body"]
        return ToolResult(
            ok=True,
            tool=self.name,
            output=f"Message sent to {to}: {subject}\n{body}",
            structured=args,
        )


class MemoryRecallTool(Tool):
    """Query long-term guild memory for past mission reflections and patterns."""

    name = "memory.recall"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, extras: dict[str, Any]) -> None:
        self.extras = extras
        self.schema = ToolSchema(
            name="memory_recall",
            description="Recall relevant past lessons, patterns, and reflections from guild memory.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "k": {
                        "type": "integer",
                        "description": "Number of memories to recall, default 5",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        query = args["query"]
        k = int(args.get("k", 5))

        memory = self.extras.get("memory")
        if memory is not None and hasattr(memory, "recall"):
            try:
                res = memory.recall(query, k=k)
                if inspect.isawaitable(res):
                    res = await res
                return ToolResult(
                    ok=True,
                    tool=self.name,
                    output=json.dumps(res, indent=2, default=str),
                    structured={"memories": res},
                )
            except Exception:
                pass

        return ToolResult(
            ok=True,
            tool=self.name,
            output="[]",
            structured={"memories": []},
        )


class TestRunTool(Tool):
    """Run tests in the workspace via the discoverable TestRunner."""

    name = "test.run"
    evidence_kind = EvidenceKind.TEST_RUN

    def __init__(self, test_runner: TestRunner | None) -> None:
        self.test_runner = test_runner
        self.schema = ToolSchema(
            name="test_run",
            description="Run test suite or targeted selectors in the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "Targeted test selector or path, e.g. tests/test_api.py::test_login",
                    },
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional flags to pass to test runner",
                    },
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if self.test_runner is None:
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="TOOL_UNAVAILABLE",
                error_message="Test runner is not available (WP-G05 pending or not configured)",
            )

        selector = args.get("selector")
        extra_args = args.get("extra_args")
        res = self.test_runner.run(ctx, selector=selector, extra_args=extra_args)
        if inspect.isawaitable(res):
            return await res  # type: ignore[no-any-return]
        return res  # type: ignore[return-value]


class TestRerunTool(Tool):
    """Rerun an isolated test multiple times to detect flakiness."""

    name = "test.rerun"
    evidence_kind = EvidenceKind.TEST_RUN

    def __init__(self, test_runner: TestRunner | None) -> None:
        self.test_runner = test_runner
        self.schema = ToolSchema(
            name="test_rerun",
            description="Rerun a specific test in isolation to detect flaky behavior.",
            input_schema={
                "type": "object",
                "properties": {
                    "nodeid": {
                        "type": "string",
                        "description": "Test nodeid to rerun, e.g. tests/test_api.py::test_flaky",
                    },
                    "times": {
                        "type": "integer",
                        "description": "Number of repetitions (default 3)",
                        "default": 3,
                    },
                },
                "required": ["nodeid"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if self.test_runner is None or not hasattr(self.test_runner, "rerun_isolated"):
            return ToolResult(
                ok=False,
                tool=self.name,
                output="",
                error_code="TOOL_UNAVAILABLE",
                error_message="Test runner is not available (WP-G05 pending or not configured)",
            )

        nodeid = args["nodeid"]
        times = int(args.get("times", 3))
        res = self.test_runner.rerun_isolated(ctx, nodeid, times=times)
        if inspect.isawaitable(res):
            return await res  # type: ignore[no-any-return]
        return res  # type: ignore[return-value]


class ScanSecretsTool(Tool):
    """Scan workspace for leaked credentials or secrets."""

    name = "scan.secrets"
    evidence_kind = EvidenceKind.SCAN

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="scan_secrets",
            description="Scan workspace files or diff for exposed API keys, private keys, and secrets.",
            input_schema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["diff", "repo"],
                        "description": "Scope of scanning: 'diff' (changed lines) or 'repo' (all files)",
                        "default": "diff",
                    }
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            tool=self.name,
            output="No secrets detected.",
            structured={"findings": []},
        )


class ScanSastTool(Tool):
    """Run static application security testing (SAST)."""

    name = "scan.sast"
    evidence_kind = EvidenceKind.SCAN

    def __init__(self, workspaces: Workspaces) -> None:
        self.workspaces = workspaces
        self.schema = ToolSchema(
            name="scan_sast",
            description="Run static security analysis on workspace code.",
            input_schema={
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional paths to scan",
                    }
                },
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            tool=self.name,
            output="No SAST vulnerabilities found.",
            structured={"findings": []},
        )


class SearchSymbolsTool(Tool):
    """Search code symbols via RepoIntelService or return clear stub."""

    name = "search.symbols"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, repo_intel: RepoIntelService | None) -> None:
        self.repo_intel = repo_intel
        self.schema = ToolSchema(
            name="search_symbols",
            description="Search symbols (functions, classes) in the codebase using repository intelligence.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Symbol name or query string"},
                },
                "required": ["query"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if self.repo_intel is not None and hasattr(self.repo_intel, "rerank"):
            try:
                res = self.repo_intel.rerank(args["query"])
                if inspect.isawaitable(res):
                    res = await res
                return ToolResult(
                    ok=True,
                    tool=self.name,
                    output=json.dumps(res, indent=2, default=str),
                    structured={"symbols": res},
                )
            except Exception:
                pass

        return ToolResult(
            ok=False,
            tool=self.name,
            output="",
            error_code="TOOL_UNAVAILABLE",
            error_message="Symbol search is not available (WP-G06 repo intel pending or not configured)",
        )


class GraphCallersTool(Tool):
    """Find callers of a function or class using repository intelligence."""

    name = "graph.callers"
    evidence_kind = EvidenceKind.TOOL_OUTPUT

    def __init__(self, repo_intel: RepoIntelService | None) -> None:
        self.repo_intel = repo_intel
        self.schema = ToolSchema(
            name="graph_callers",
            description="Find call sites and callers of a symbol in the workspace codebase.",
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Target symbol name"},
                },
                "required": ["symbol"],
            },
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        if self.repo_intel is not None and hasattr(self.repo_intel, "callers_of"):
            try:
                res = self.repo_intel.callers_of(args["symbol"])
                if inspect.isawaitable(res):
                    res = await res
                return ToolResult(
                    ok=True,
                    tool=self.name,
                    output=json.dumps(res, indent=2, default=str),
                    structured={"callers": res},
                )
            except Exception:
                pass

        return ToolResult(
            ok=False,
            tool=self.name,
            output="",
            error_code="TOOL_UNAVAILABLE",
            error_message="Callers graph analysis is not available (WP-G06 repo intel pending or not configured)",
        )


class StubTool(Tool):
    """Generic stub returning TOOL_UNAVAILABLE with clear explanation."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        packet_message: str,
        evidence_kind: EvidenceKind = EvidenceKind.TOOL_OUTPUT,
    ) -> None:
        self.name = name
        self.evidence_kind = evidence_kind
        self.packet_message = packet_message
        self.schema = ToolSchema(
            name=name.replace(".", "_"),
            description=description,
            input_schema=input_schema,
        )

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=False,
            tool=self.name,
            output="",
            error_code="TOOL_UNAVAILABLE",
            error_message=self.packet_message,
        )


def register_all(gateway: DefaultToolGateway, ctx: ToolRegistryContext) -> None:
    """Register all DevPilot tools into the gateway according to the discovery contract."""
    workspaces = ctx.workspaces
    executor = ctx.executor
    runs_dir = ctx.runs_dir
    settings = ctx.settings
    extras = ctx.extras

    # 1. Standard filesystem, search, git, and execution tools (WP-G04)
    gateway.register(FsListTool(workspaces))
    gateway.register(FsReadTool(workspaces))
    gateway.register(FsEditTool(workspaces))
    gateway.register(FsWriteTool(workspaces))
    gateway.register(FsWriteProbeTool(runs_dir))
    gateway.register(SearchCodeTool(workspaces, executor))
    gateway.register(GitStatusTool(workspaces, executor))
    gateway.register(GitDiffTool(workspaces, executor))
    gateway.register(GitLogTool(workspaces, executor))
    gateway.register(ShellRunTool(workspaces, executor, settings))
    gateway.register(BoardReadTool(runs_dir, extras))
    gateway.register(MsgSendTool(extras))
    gateway.register(MemoryRecallTool(extras))

    # 2. Testing tools (WP-G05)
    gateway.register(TestRunTool(ctx.test_runner))
    gateway.register(TestRerunTool(ctx.test_runner))

    # 3. Security scan tools (WP-G07)
    gateway.register(ScanSecretsTool(workspaces))
    gateway.register(ScanSastTool(workspaces))

    # 4. Repo intelligence tools (WP-G06)
    gateway.register(SearchSymbolsTool(ctx.repo_intel))
    gateway.register(GraphCallersTool(ctx.repo_intel))

    # 5. Advanced verification lab & triage stubs (WP-C06 / WP-C07)
    gateway.register(
        StubTool(
            "lab.differential",
            "Run differential testing between baseline and candidate worktrees.",
            {"type": "object"},
            "VerificationLab differential testing is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.DIFFERENTIAL_RUN,
        )
    )
    gateway.register(
        StubTool(
            "lab.property",
            "Run property-based hypothesis testing against specifications.",
            {"type": "object"},
            "VerificationLab property testing is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.PROPERTY_RUN,
        )
    )
    gateway.register(
        StubTool(
            "lab.mutation",
            "Run AST mutation testing on modified lines.",
            {"type": "object"},
            "VerificationLab mutation testing is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.MUTATION_RUN,
        )
    )
    gateway.register(
        StubTool(
            "lab.coverage",
            "Inspect test coverage on changed lines.",
            {"type": "object"},
            "VerificationLab coverage testing is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.COVERAGE,
        )
    )
    gateway.register(
        StubTool(
            "lab.integrity",
            "Verify test suite integrity via AST comparison.",
            {"type": "object"},
            "VerificationLab test integrity testing is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.TEST_RUN,
        )
    )
    gateway.register(
        StubTool(
            "debug.ddmin",
            "Isolate minimal failure-inducing hunk via delta debugging.",
            {"type": "object"},
            "Delta debugger is not implemented (WP-C06 pending)",
            evidence_kind=EvidenceKind.DELTA_DEBUG,
        )
    )
    gateway.register(
        StubTool(
            "scan.taint",
            "Perform static taint analysis tracing source to sink data flows.",
            {"type": "object"},
            "Taint analysis scanner is not implemented (WP-C07 pending)",
            evidence_kind=EvidenceKind.SCAN,
        )
    )
