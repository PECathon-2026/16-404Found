"""Secret scanner: regex-based search for API keys, passwords, and unsafe code patterns."""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Patterns that indicate secrets or dangerous code
# ---------------------------------------------------------------------------

SECRET_PATTERNS = [
    (re.compile(r'(?i)(api[_-]?key|secret|password|passwd|token|private[_-]?key)\s*=\s*["\'][^"\']{8,}["\']'), "hardcoded_secret"),
    (re.compile(r'sk_live_[A-Za-z0-9]{10,}'), "stripe_live_key"),
    (re.compile(r'sk_test_[A-Za-z0-9]{10,}'), "stripe_test_key"),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "aws_access_key"),
    (re.compile(r'-----BEGIN (RSA |EC )?PRIVATE KEY-----'), "private_key_pem"),
    (re.compile(r'ghp_[A-Za-z0-9]{36,}'), "github_pat"),
    (re.compile(r'(?i)password\s*=\s*["\'][^"\']{4,}["\']'), "hardcoded_password"),
]

UNSAFE_CODE_PATTERNS = [
    (re.compile(r'\beval\s*\('), "use_of_eval"),
    (re.compile(r'\bexec\s*\('), "use_of_exec"),
    (re.compile(r'["\'].*SELECT.*["\'].*\+'), "string_built_sql"),
    (re.compile(r'["\'].*INSERT.*["\'].*\+'), "string_built_sql"),
    (re.compile(r'["\'].*UPDATE.*["\'].*\+'), "string_built_sql"),
    (re.compile(r'["\'].*DELETE.*["\'].*\+'), "string_built_sql"),
    (re.compile(r'subprocess\.call\(.*shell\s*=\s*True'), "shell_injection_risk"),
    (re.compile(r'os\.system\('), "os_system_call"),
]


def scan_file(filepath: str | Path) -> list[dict]:
    """
    Scan a single file for secrets and unsafe patterns.

    Returns list of {file, line, pattern_type, match_text, category}.
    """
    path = Path(filepath)
    if not path.is_file():
        return []

    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, ptype in SECRET_PATTERNS:
            m = pattern.search(line)
            if m:
                findings.append(
                    {
                        "file": str(path),
                        "line": i,
                        "pattern_type": ptype,
                        "match_text": m.group(0)[:80],
                        "category": "secret",
                    }
                )
        for pattern, ptype in UNSAFE_CODE_PATTERNS:
            m = pattern.search(line)
            if m:
                findings.append(
                    {
                        "file": str(path),
                        "line": i,
                        "pattern_type": ptype,
                        "match_text": m.group(0)[:80],
                        "category": "unsafe_code",
                    }
                )
    return findings


def scan_directory(dirpath: str | Path, file_glob: str = "*.py") -> list[dict]:
    """
    Recursively scan all matching files in dirpath.

    Returns aggregated list of findings from scan_file.
    """
    import fnmatch
    import os

    dirpath = Path(dirpath)
    all_findings = []
    for root, _dirs, files in os.walk(dirpath):
        for fname in files:
            if fnmatch.fnmatch(fname, file_glob):
                fpath = Path(root) / fname
                all_findings.extend(scan_file(fpath))
    return all_findings
