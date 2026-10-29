"""Parallel scheduling (docs/04 section 8): which tasks may run now, and which can run together. Pure."""

from __future__ import annotations

from devpilot.core.models import Mission, Task, TaskStatus


def ready_tasks(mission: Mission) -> list[Task]:
    """Tasks that are READY, or PENDING with every dependency DONE. Stable (plan) order."""
    out: list[Task] = []
    for task in mission.tasks.values():
        if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
            continue
        deps = [mission.tasks.get(d) for d in task.depends_on]
        if all(d is not None and d.status == TaskStatus.DONE for d in deps):
            out.append(task)
    return out


def batch(ready: list[Task], max_parallel: int) -> list[Task]:
    """Greedy batch of at most ``max_parallel`` tasks whose ``files_to_touch`` are pairwise disjoint.

    A task with no ``files_to_touch`` claims nothing and never conflicts. At least one task is returned
    whenever ``ready`` is non-empty (``max_parallel`` is clamped to 1).
    """
    limit = max(1, max_parallel)
    chosen: list[Task] = []
    claimed: set[str] = set()
    for task in ready:
        if len(chosen) >= limit:
            break
        files = set(task.files_to_touch)
        if claimed.isdisjoint(files):
            chosen.append(task)
            claimed |= files
    return chosen
