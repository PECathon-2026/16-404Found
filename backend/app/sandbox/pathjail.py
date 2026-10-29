"""Repository path isolation (G1). Every file access from an agent goes through `resolve_in`."""
from __future__ import annotations

import os
from pathlib import Path


class PathViolation(Exception):
    pass


PROTECTED_TOP = {".git"}


def resolve_in(root: Path, rel: str, *, for_write: bool = False) -> Path:
    """Resolve `rel` under `root` or raise PathViolation.

    Rejects: absolute paths, NUL bytes, `~`, `..` escapes, symlinks that resolve outside, and `.git` internals.
    """
    if rel is None or "\x00" in rel:
        raise PathViolation("invalid path")
    if rel.startswith("~"):
        raise PathViolation("home-relative paths are not allowed")
    p = Path(rel)
    if p.is_absolute():
        raise PathViolation("absolute paths are not allowed")
    root_real = Path(os.path.realpath(root))
    joined = root_real / p
    # Normalise lexically first so that a/../../x is caught even if intermediate dirs do not exist.
    norm = Path(os.path.normpath(joined))
    if norm != root_real and root_real not in norm.parents:
        raise PathViolation("path escapes the workspace")
    # Then resolve symlinks on the deepest existing ancestor.
    probe = norm
    while not probe.exists() and probe != root_real:
        probe = probe.parent
    real = Path(os.path.realpath(probe))
    if real != root_real and root_real not in real.parents:
        raise PathViolation("symlink resolves outside the workspace")
    if for_write and norm.is_symlink():
        raise PathViolation("refusing to write through a symlink")
    rel_parts = norm.relative_to(root_real).parts
    if rel_parts and rel_parts[0] in PROTECTED_TOP:
        raise PathViolation(".git internals are not accessible")
    return norm
