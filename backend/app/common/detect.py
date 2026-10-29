"""Repository reconnaissance helpers: language, framework and command detection (deterministic)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Syntax check that never writes bytecode. `python -m compileall` writes .pyc files even with
# PYTHONDONTWRITEBYTECODE=1; a same-size edit in the same second as that write then runs STALE bytecode
# (false failures/passes). This was found by a flaky end-to-end run; see tests/integration/test_tools.py.
SYNTAX_CHECK = (
    "import ast,sys,pathlib\n"
    "skip={'.git','node_modules','.venv','venv','__pycache__'}\n"
    "bad=[]\n"
    "for p in sorted(pathlib.Path('.').rglob('*.py')):\n"
    "    if skip & set(p.parts): continue\n"
    "    try: ast.parse(p.read_text('utf-8'), str(p))\n"
    "    except SyntaxError as e: bad.append(f'{p}:{e.lineno}: SyntaxError: {e.msg}')\n"
    "    except UnicodeDecodeError: pass\n"
    "print('\\n'.join(bad)); sys.exit(1 if bad else 0)\n"
)


def purge_pycache(root: Path) -> None:
    """Remove bytecode caches so a test run can never execute stale code (mtime has 1s granularity)."""
    import shutil

    for d in list(root.rglob("__pycache__")):
        if d.is_dir() and not d.is_symlink() and root in d.resolve().parents:
            shutil.rmtree(d, ignore_errors=True)


SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build"}
EXT_LANG = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
            ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php", ".cs": "csharp"}


def iter_files(ws: Path, limit: int = 3000):
    n = 0
    for p in sorted(ws.rglob("*")):
        if any(part in SKIP for part in p.relative_to(ws).parts):
            continue
        if p.is_file() and not p.is_symlink():
            yield p
            n += 1
            if n >= limit:
                return


def detect(ws: Path) -> dict[str, Any]:
    langs: dict[str, int] = {}
    files = list(iter_files(ws))
    for p in files:
        lang = EXT_LANG.get(p.suffix)
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
    pyproject = (ws / "pyproject.toml").read_text("utf-8", "replace") if (ws / "pyproject.toml").exists() else ""
    reqs = ""
    for name in ("requirements.txt", "requirements-dev.txt"):
        if (ws / name).exists():
            reqs += (ws / name).read_text("utf-8", "replace")
    py_text = (pyproject + reqs).lower()
    frameworks = [f for f in ("fastapi", "flask", "django", "pytest", "sqlalchemy", "pydantic") if f in py_text]
    if not frameworks:  # fall back to import scan (small repos often have no manifest)
        blob = ""
        for p in files:
            if p.suffix == ".py":
                blob += p.read_text("utf-8", "replace")[:4000].lower()
        frameworks = [f for f in ("fastapi", "flask", "django", "pytest", "sqlalchemy", "pydantic") if f"import {f}" in blob or f"from {f}" in blob]
    cmds: dict[str, Any] = {"test": None, "lint": None, "build": None, "alternatives": []}
    has_pytest_cfg = (ws / "pytest.ini").exists() or "[tool.pytest" in pyproject or (ws / "conftest.py").exists()
    py_tests = [p for p in files if p.suffix == ".py" and (p.name.startswith("test_") or p.name.endswith("_test.py"))]
    pkg: dict[str, Any] = {}
    if (ws / "package.json").exists():
        try:
            pkg = json.loads((ws / "package.json").read_text("utf-8"))
        except json.JSONDecodeError:
            pkg = {}
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    if py_tests or has_pytest_cfg:
        cmds["test"] = {"runner": "pytest", "argv": ["python", "-m", "pytest", "-q"]}
        cmds["alternatives"].append({"runner": "unittest", "argv": ["python", "-m", "unittest", "discover", "-v"]})
    if scripts.get("test") and "no test specified" not in scripts["test"]:
        node = {"runner": "npm", "argv": ["npm", "test"]}
        if cmds["test"] is None:
            cmds["test"] = node
        else:
            cmds["alternatives"].append(node)
    if "[tool.ruff" in pyproject or (ws / "ruff.toml").exists():
        cmds["lint"] = {"runner": "ruff", "argv": ["python", "-m", "ruff", "check", "."]}
    elif scripts.get("lint"):
        cmds["lint"] = {"runner": "npm", "argv": ["npm", "run", "lint"]}
    if langs.get("python"):
        cmds["build"] = {"runner": "syntax", "argv": ["python", "-c", SYNTAX_CHECK]}
    elif scripts.get("build"):
        cmds["build"] = {"runner": "npm", "argv": ["npm", "run", "build"]}
    line_len = None
    m = re.search(r"line-length\s*=\s*(\d+)", pyproject)
    if m:
        line_len = int(m.group(1))
    test_dirs = sorted({str(p.parent.relative_to(ws)) or "." for p in py_tests})
    conventions = {
        "line_length": line_len, "test_dirs": test_dirs,
        "style": "ruff" if "[tool.ruff" in pyproject else ("black" if "black" in py_text else None),
        "uses_type_hints": any("->" in p.read_text("utf-8", "replace")[:3000] for p in files if p.suffix == ".py"),
    }
    entry = [str(p.relative_to(ws)) for p in files if p.name in {"main.py", "app.py", "manage.py", "__main__.py", "index.js", "server.js"}][:5]
    return {
        "languages": langs, "frameworks": frameworks, "detected_commands": cmds, "conventions": conventions,
        "entry_points": entry, "file_count": len(files),
    }
