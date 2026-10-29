"""Deterministic security scanners (T2.11): secrets, risky patterns, prompt-injection heuristics."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from .detect import SKIP
from .redact import mask
from .tamper import is_test_path

TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".md", ".txt",
            ".sh", ".html", ".go", ".rb", ".php", ".java", ".cs", ".rs", ""}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".php", ".java", ".cs"}

SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("api_key_prefix", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("hardcoded_credential", re.compile(
        r"""(?ix)\b[A-Z0-9_]*(?:secret|passw(?:or)?d|api[_-]?key|token|private[_-]?key|access[_-]?key)[A-Z0-9_]*\s*[:=]\s*(["'])(?!\s*\1)([^"'\n]{8,})\1""")),
]
PLACEHOLDER = re.compile(r"(?i)^(changeme|change[-_ ]me|your[-_ ]|<.*>|\$\{.*\}|xxx+|example|placeholder|test|dummy|\*+$|os\.environ|getenv)")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {c: s.count(c) / len(s) for c in set(s)}
    return -sum(p * math.log2(p) for p in freq.values())


PATTERN_RULES: list[dict[str, Any]] = [
    dict(id="sql_fstring", cat="SQL_INJECTION", cwe="CWE-89", sev="HIGH", exts={".py"},
         rx=r"""(?i)(execute|executemany|raw|text)\(\s*f["'][^"']*\b(select|insert|update|delete)\b""",
         fix="Use parameterised queries (placeholders + bound parameters); never build SQL with f-strings."),
    dict(id="sql_concat", cat="SQL_INJECTION", cwe="CWE-89", sev="HIGH", exts={".py", ".js", ".ts"},
         rx=r"""(?i)\b(select|insert|update|delete)\b[^\n"']*["']\s*(\+|%|\.format\()|(execute)\(\s*["'][^"']*["']\s*(%|\+|\.format)""",
         fix="Use parameterised queries instead of string concatenation/formatting."),
    dict(id="sql_fstring_var", cat="SQL_INJECTION", cwe="CWE-89", sev="HIGH", exts={".py"},
         rx=r"""(?i)f["'][^"'\n]*\b(select|insert|update|delete)\b[^"'\n]*\{[^}]+\}""",
         fix="Use parameterised queries instead of interpolating values into SQL."),
    dict(id="shell_true", cat="COMMAND_INJECTION", cwe="CWE-78", sev="HIGH", exts={".py"},
         rx=r"subprocess\.\w+\([^)]*shell\s*=\s*True", fix="Pass an argv list and keep shell=False."),
    dict(id="os_system", cat="COMMAND_INJECTION", cwe="CWE-78", sev="HIGH", exts={".py"},
         rx=r"\bos\.(system|popen)\(", fix="Use subprocess.run with an argv list (no shell)."),
    dict(id="js_exec", cat="COMMAND_INJECTION", cwe="CWE-78", sev="HIGH", exts={".js", ".ts"},
         rx=r"child_process\.exec\(|\bexecSync\(", fix="Use execFile/spawn with an argument array."),
    dict(id="eval_exec", cat="CODE_EXECUTION", cwe="CWE-95", sev="HIGH", exts={".py", ".js", ".ts"},
         rx=r"(?<![.\w])(eval|exec)\(", fix="Remove eval/exec; parse data with a safe parser (json, ast.literal_eval)."),
    dict(id="pickle", cat="UNSAFE_DESERIALIZATION", cwe="CWE-502", sev="HIGH", exts={".py"},
         rx=r"\b(pickle|cPickle|marshal)\.loads?\(", fix="Use JSON or another safe format for untrusted data."),
    dict(id="yaml_load", cat="UNSAFE_DESERIALIZATION", cwe="CWE-502", sev="HIGH", exts={".py"},
         rx=r"\byaml\.load\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)(?![^)]*SafeLoader)", fix="Use yaml.safe_load."),
    dict(id="tls_verify", cat="TLS_VERIFY_DISABLED", cwe="CWE-295", sev="MEDIUM", exts={".py"},
         rx=r"verify\s*=\s*False", fix="Keep certificate verification enabled."),
    dict(id="debug_true", cat="DEBUG_ENABLED", cwe="CWE-489", sev="MEDIUM", exts={".py"},
         rx=r"(?<!\w)(DEBUG|debug)\s*=\s*True", fix="Disable debug mode outside local development; read it from config."),
    dict(id="weak_hash_pw", cat="WEAK_CRYPTO", cwe="CWE-327", sev="HIGH", exts={".py"},
         rx=r"(?i)hashlib\.(md5|sha1)\([^)\n]*(pass|pwd)", fix="Hash passwords with bcrypt/argon2/scrypt (e.g. passlib), not md5/sha1."),
    dict(id="weak_hash", cat="WEAK_CRYPTO", cwe="CWE-327", sev="LOW", exts={".py"},
         rx=r"hashlib\.(md5|sha1)\(", fix="Prefer sha256+ unless required for compatibility."),
    dict(id="jwt_noverify", cat="JWT_MISUSE", cwe="CWE-347", sev="HIGH", exts={".py"},
         rx=r"""(verify(_signature)?["']?\s*[:=]\s*False)|(algorithms\s*=\s*\[\s*["']none["'])""",
         fix="Always verify JWT signatures and pin allowed algorithms."),
    dict(id="cors_any", cat="PERMISSIVE_CORS", cwe="CWE-942", sev="MEDIUM", exts={".py"},
         rx=r"""allow_origins\s*=\s*\[\s*["']\*["']""", fix="Restrict CORS to the exact origins that need access."),
    dict(id="path_join_request", cat="PATH_TRAVERSAL", cwe="CWE-22", sev="MEDIUM", exts={".py"},
         rx=r"os\.path\.join\([^)\n]*(request|req)\.", fix="Validate/normalise user-supplied paths and enforce a base directory."),
    dict(id="inner_html", cat="XSS", cwe="CWE-79", sev="MEDIUM", exts={".js", ".ts", ".tsx", ".jsx"},
         rx=r"\.innerHTML\s*=|dangerouslySetInnerHTML", fix="Avoid raw HTML injection; render text or sanitise."),
]
_COMPILED = [(r, re.compile(r["rx"])) for r in PATTERN_RULES]

INJECTION = re.compile(
    r"(?i)(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous) (prompt|instructions)|"
    r"\bAI (agents?|assistants?|models?)\s*[:,]\s*(please )?(run|execute|ignore|send|delete)|"
    r"(curl|wget)\s+\S+\s*\|\s*(sh|bash)|you are now (in )?(developer|admin) mode|reveal (your )?(system prompt|api key))")


def fingerprint(rule: str, file: str, line_text: str) -> str:
    norm = re.sub(r"\s+", " ", line_text.strip())
    return hashlib.sha1(f"{rule}|{file}|{norm}".encode()).hexdigest()[:16]


def _files(ws: Path, paths: list[str] | None):
    if paths:
        for p in paths:
            f = ws / p
            if f.is_file() and not f.is_symlink():
                yield f
        return
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws)
        if any(part in SKIP for part in rel.parts) or not p.is_file() or p.is_symlink():
            continue
        if p.suffix in TEXT_EXT and p.stat().st_size < 400_000:
            yield p


def scan_secrets(ws: Path, paths: list[str] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in _files(ws, paths):
        rel = str(f.relative_to(ws))
        if rel.endswith(".example") or "/fixtures/" in rel:
            continue
        try:
            lines = f.read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for name, rx in SECRET_RULES:
                m = rx.search(line)
                if not m:
                    continue
                value = m.group(m.lastindex) if name == "hardcoded_credential" and m.lastindex else m.group(0)
                if name == "hardcoded_credential":
                    if PLACEHOLDER.search(value) or "environ" in line or "getenv" in line or "os.getenv" in line:
                        continue
                    if len(set(value)) < 4 and _entropy(value) < 2.0:
                        continue
                is_test = is_test_path(rel)
                out.append({
                    "rule": name, "category": "HARDCODED_SECRET", "cwe": "CWE-798", "file": rel, "line": i,
                    "severity": "MEDIUM" if is_test else "HIGH", "masked": mask(value),
                    "evidence": redact_line(line), "fingerprint": fingerprint(name, rel, re.sub(re.escape(value), "<v>", line)),
                    "recommendation": "Remove the secret from source; read it from the environment/secret store and rotate it.",
                    "confidence": 0.95 if name != "hardcoded_credential" else 0.8,
                })
                break
    return out


def redact_line(line: str) -> str:
    from .redact import redact

    return redact(line.strip())[0][:240]


def scan_patterns(ws: Path, paths: list[str] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in _files(ws, paths):
        if f.suffix not in CODE_EXT:
            continue
        rel = str(f.relative_to(ws))
        is_test = is_test_path(rel)
        try:
            lines = f.read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        seen: set[tuple[str, int]] = set()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith(("#", "//")):
                continue
            for rule, rx in _COMPILED:
                if f.suffix not in rule["exts"] or not rx.search(line):
                    continue
                if rule["id"] == "sql_concat" and "sql_fstring" in {r for r, _ in seen}:
                    continue
                key = (rule["cat"], i)
                if key in seen:
                    continue
                seen.add(key)
                sev = rule["sev"]
                if is_test and sev in {"HIGH", "MEDIUM"}:
                    sev = "LOW"
                out.append({
                    "rule": rule["id"], "category": rule["cat"], "cwe": rule["cwe"], "file": rel, "line": i, "severity": sev,
                    "evidence": redact_line(line), "fingerprint": fingerprint(rule["id"], rel, line),
                    "recommendation": rule["fix"], "confidence": 0.85,
                })
    return out


def scan_injection(ws: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in _files(ws, None):
        rel = str(f.relative_to(ws))
        try:
            lines = f.read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if INJECTION.search(line):
                out.append({
                    "rule": "prompt_injection", "category": "PROMPT_INJECTION", "cwe": "CWE-1427", "file": rel, "line": i,
                    "severity": "LOW", "evidence": redact_line(line), "fingerprint": fingerprint("pi", rel, line),
                    "recommendation": "Treat this text as untrusted data. DevPilot did not follow it; remove it from the repository.",
                    "confidence": 0.7,
                })
    return out


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)")


def quality_review(patch: str, line_length: int | None = None) -> list[dict[str, Any]]:
    """Deterministic code-review heuristics on *added* lines (readability, consistency, regression risk). Never blocking (LOW)."""
    limit = line_length or 120
    out: list[dict[str, Any]] = []
    cur = None
    n = 0
    new_defs: list[tuple[str, int, str]] = []
    changed_files: list[str] = []
    for ln in patch.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
            changed_files.append(cur)
            continue
        h = _HUNK.match(ln)
        if h:
            n = int(h.group(1))
            continue
        if cur is None or not ln.startswith("+") or ln.startswith("+++"):
            if cur is not None and ln.startswith(" "):
                n += 1
            continue
        text = ln[1:]
        lineno, n = n, n + 1
        is_py = cur.endswith(".py")
        is_test = is_test_path(cur)

        def add(rule: str, cat: str, why: str) -> None:
            out.append({"rule": rule, "category": cat, "cwe": None, "file": cur, "line": lineno, "severity": "LOW", "evidence": redact_line(text),
                        "fingerprint": fingerprint(rule, cur or "", text), "recommendation": why, "confidence": 0.7, "scope": "changed"})

        if is_py and re.match(r"^\s*except\s*:", text):
            add("bare_except", "CODE_QUALITY", "Catch specific exceptions; a bare except hides real errors.")
        if is_py and not is_test and re.match(r"^\s*print\(", text):
            add("debug_print", "CODE_QUALITY", "Use logging instead of print in library code.")
        if re.search(r"#\s*(TODO|FIXME|XXX|HACK)\b", text):
            add("todo", "CODE_QUALITY", "Resolve or track the TODO instead of shipping it.")
        if len(text) > limit and not text.lstrip().startswith(("#", "http")):
            add("long_line", "CODE_QUALITY", f"Line is {len(text)} chars; the project's limit is {limit}.")
        m = re.match(r"^\s*(?:async\s+)?def\s+([A-Za-z]\w*)\(", text)
        if m and is_py and not is_test and not m.group(1).startswith("_"):
            new_defs.append((cur, lineno, text))
    if new_defs and not any(is_test_path(f) for f in changed_files):
        f, ln_, text = new_defs[0]
        out.append({"rule": "missing_tests", "category": "TEST_COVERAGE", "cwe": None, "file": f, "line": ln_, "severity": "LOW", "evidence": redact_line(text),
                    "fingerprint": fingerprint("missing_tests", f, "new public function without tests"),
                    "recommendation": "New public functions were added but no test file changed; add tests (regression risk).", "confidence": 0.6, "scope": "changed"})
    return out
