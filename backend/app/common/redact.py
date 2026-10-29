"""Secret redaction (G5). Applied to tool output, logs, findings and events before storage/display."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("assignment", re.compile(
        r"""(?ix)\b([A-Z0-9_]*(?:secret|passw(?:or)?d|api[_-]?key|token|private[_-]?key|access[_-]?key)[A-Z0-9_]*)\s*[:=]\s*(["'])([^"'\n]{8,})\2""")),
]


def mask(value: str) -> str:
    return f"{value[:2]}…{value[-2:]}" if len(value) > 6 else "…"


def redact(text: str, extra_secrets: list[str] | None = None) -> tuple[str, int]:
    count = 0

    def sub_simple(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"[REDACTED:{mask(m.group(0))}]"

    for name, pat in PATTERNS:
        if name == "assignment":
            def sub_assign(m: re.Match[str]) -> str:
                nonlocal count
                count += 1
                return f"{m.group(1)} = {m.group(2)}[REDACTED:{mask(m.group(3))}]{m.group(2)}"
            text = pat.sub(sub_assign, text)
        else:
            text = pat.sub(sub_simple, text)
    for s in extra_secrets or []:
        if s and len(s) >= 8 and s in text:
            count += text.count(s)
            text = text.replace(s, f"[REDACTED:{mask(s)}]")
    return text, count
