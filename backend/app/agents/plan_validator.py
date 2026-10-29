"""Plan validator (T3.05): acyclic DAG, every criterion verifiable and covered, no dangling refs."""
from __future__ import annotations

from .schemas import PlanResult


def validate_plan(plan: PlanResult) -> list[str]:
    errs: list[str] = []
    if any(a.blocking for a in plan.ambiguities):
        return [] if all(a.question.strip() for a in plan.ambiguities if a.blocking) else ["blocking ambiguity needs a concrete question"]
    if not plan.acceptance_criteria:
        errs.append("no acceptance criteria")
    if not plan.tasks:
        errs.append("no tasks")
    cids = [c.id for c in plan.acceptance_criteria]
    if len(set(cids)) != len(cids):
        errs.append("duplicate criterion ids")
    for c in plan.acceptance_criteria:
        v = c.verification
        if v.method == "test_selector" and not v.selectors:
            errs.append(f"{c.id}: test_selector needs selectors")
        if v.method == "command" and not v.argv:
            errs.append(f"{c.id}: command needs argv")
        if v.method == "static_check" and not (v.path and (v.must_match or v.must_not_match)):
            errs.append(f"{c.id}: static_check needs path and must_match/must_not_match")
        if v.method == "manual_review" and not v.rubric:
            errs.append(f"{c.id}: manual_review needs a rubric")
    refs = [t.ref for t in plan.tasks]
    if len(set(refs)) != len(refs):
        errs.append("duplicate task refs")
    covered: set[str] = set()
    for t in plan.tasks:
        for d in t.depends_on:
            if d not in refs:
                errs.append(f"{t.ref}: depends on unknown task {d}")
        for c in t.criteria:
            if c not in cids:
                errs.append(f"{t.ref}: references unknown criterion {c}")
            covered.add(c)
        if not t.files_hint:
            errs.append(f"{t.ref}: files_hint is empty (name the files you expect to touch or create)")
    for c in cids:
        if c not in covered:
            errs.append(f"{c} is not covered by any task")
    # cycle check (Kahn)
    indeg = {r: 0 for r in refs}
    adj: dict[str, list[str]] = {r: [] for r in refs}
    for t in plan.tasks:
        for d in t.depends_on:
            if d in adj:
                adj[d].append(t.ref)
                indeg[t.ref] += 1
    queue = [r for r, n in indeg.items() if n == 0]
    seen = 0
    while queue:
        n = queue.pop()
        seen += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if seen != len(refs):
        errs.append("task dependencies contain a cycle")
    return errs
