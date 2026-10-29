"""Watchdog (AGENTS.md §E.7): deterministic loop/limit enforcement. Runs before every master decision."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..common.parsers import fingerprint

DEFAULTS = {"max_repair_cycles": 8, "max_replans": 2, "max_steps": 60, "max_wall_clock_min": 20, "same_fingerprint_limit": 3,
            "max_tokens": 400_000}


@dataclass
class Verdict:
    force: str  # "ESCALATE" | "FAIL"
    reason: str
    kind: str   # REPEATED_FAILURE | REPAIR_LIMIT | REPLAN_LIMIT | STEP_LIMIT | WALL_CLOCK | BUDGET
    evidence: list[dict[str, Any]]


def limits(mission: dict[str, Any]) -> dict[str, Any]:
    lim = dict(DEFAULTS)
    lim.update((mission["config"] or {}).get("limits") or {})
    lim["max_repair_cycles"] += int((mission["config"] or {}).get("_extra_repair_cycles", 0))
    return lim


def trailing_fingerprint(test_runs: list[dict[str, Any]], after_id: str | None = None) -> tuple[str | None, int, list[str]]:
    """(fingerprint, consecutive count, run ids) of the most recent RED TEST runs sharing one failure fingerprint."""
    runs = [r for r in test_runs if r["kind"] == "TEST" and (after_id is None or r["id"] > after_id)]
    fp, n, ids = None, 0, []
    for r in reversed(runs):
        if r["outcome"] not in ("RED", "ERROR") or not r["failures"]:
            break
        cur = fingerprint(r["failures"])
        if fp is None:
            fp = cur
        if cur != fp:
            break
        n += 1
        ids.append(r["id"])
    return fp, n, ids


def check(mission: dict[str, Any], test_runs: list[dict[str, Any]]) -> Verdict | None:
    lim = limits(mission)
    cfg = mission["config"] or {}
    if mission["steps"] >= lim["max_steps"]:
        return Verdict("FAIL", f"step limit reached ({mission['steps']}/{lim['max_steps']})", "STEP_LIMIT", [])
    if mission["tokens_used"] >= lim["max_tokens"]:
        return Verdict("ESCALATE", f"token budget exhausted ({mission['tokens_used']}/{lim['max_tokens']})", "BUDGET", [])
    start = cfg.get("_clock_start")
    if start and (time.time() - start) > lim["max_wall_clock_min"] * 60:
        return Verdict("ESCALATE", f"wall-clock limit of {lim['max_wall_clock_min']} min reached", "WALL_CLOCK", [])
    fp, n, ids = trailing_fingerprint(test_runs, cfg.get("_fp_reset_after"))
    if fp and n >= lim["same_fingerprint_limit"]:
        return Verdict("ESCALATE", f"the same failure ({fp}) occurred {n} times in a row with no progress", "REPEATED_FAILURE",
                       [{"kind": "test_run", "id": i} for i in ids])
    if mission["repair_cycles"] >= lim["max_repair_cycles"]:
        return Verdict("ESCALATE", f"repair-cycle limit reached ({mission['repair_cycles']}/{lim['max_repair_cycles']})", "REPAIR_LIMIT", [])
    return None
