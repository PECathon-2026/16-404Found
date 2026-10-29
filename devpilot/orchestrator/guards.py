"""Hard guards that bound autonomy (docs/04 section 6.3, docs/11 section 9). Pure: no I/O, no LLM.

``legal_actions`` computes the action set the Shogun may choose from (illegal options are never
offered). ``override`` is the second line of defence: it validates the Shogun's actual choice and, if
it is not legal, replaces it and says which guard did so. Both read the same ``_evaluate`` so they can
never disagree.

The Blackboard projector does not track ``fix_cycles``, ``tournaments`` or wall-clock time, so the
orchestrator passes its own ``GuardCounters``; unset fields fall back to ``mission.budget``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from devpilot.core.models import (
    Action,
    BudgetState,
    Decision,
    LegalAction,
    Mission,
    ProgressVector,
    Task,
)
from devpilot.orchestrator.progress import badness, trend

#: Order in which a replacement action is chosen when the Shogun's choice is illegal.
PREFERENCE: tuple[Action, ...] = (
    Action.INVESTIGATE,
    Action.REASSIGN,
    Action.ESCALATE_MODEL,
    Action.REPLAN,
    Action.TOURNAMENT,
    Action.ROLLBACK,
    Action.RETRY_SAME_AGENT,
    Action.ASK_HUMAN,
    Action.STOP_PARTIAL,
)
RETRY_LIKE: frozenset[Action] = frozenset({Action.RETRY_SAME_AGENT, Action.REASSIGN, Action.ESCALATE_MODEL})

#: Default cost of an action when the mission has no history for it: (tokens, seconds).
DEFAULT_COST: dict[Action, tuple[int, int]] = {
    Action.RETRY_SAME_AGENT: (40_000, 180),
    Action.REASSIGN: (60_000, 240),
    Action.ESCALATE_MODEL: (80_000, 240),
    Action.INVESTIGATE: (30_000, 120),
    Action.REPLAN: (50_000, 150),
    Action.TOURNAMENT: (150_000, 420),
    Action.ROLLBACK: (40_000, 180),
    Action.ASK_HUMAN: (0, 60),
    Action.STOP_PARTIAL: (0, 0),
    Action.ABORT: (0, 0),
}
#: Which past mode invocations estimate which action, and how many times that mode is run.
COST_MODE: dict[Action, tuple[str, int]] = {
    Action.RETRY_SAME_AGENT: ("samurai.rework", 1),
    Action.REASSIGN: ("samurai.implement", 1),
    Action.ESCALATE_MODEL: ("samurai.rework", 1),
    Action.INVESTIGATE: ("scout.investigate", 1),
    Action.REPLAN: ("shogun.plan", 1),
    Action.TOURNAMENT: ("samurai.explore", 3),
    Action.ROLLBACK: ("samurai.rework", 1),
}


@dataclass(frozen=True, slots=True)
class GuardCounters:
    """Orchestrator-side counters the event projection does not carry. ``None`` = use ``mission.budget``."""

    fix_cycles: int | None = None
    tournaments: int | None = None
    wall_clock_s: float | None = None


def effective_budget(mission: Mission, counters: GuardCounters | None = None) -> BudgetState:
    """``mission.budget`` with the orchestrator's counters applied (a copy; the mission is untouched)."""
    b = mission.budget.model_copy(deep=True)
    if counters is not None:
        if counters.fix_cycles is not None:
            b.fix_cycles = counters.fix_cycles
        if counters.tournaments is not None:
            b.tournaments = counters.tournaments
        if counters.wall_clock_s is not None:
            b.wall_clock_s = counters.wall_clock_s
    b.replans = max(b.replans, len(mission.plans) - 1, 0)
    return b


def fingerprint_repeats(task: Task | None) -> int:
    """How many attempts of the task carry (any of) the fingerprints of its latest attempt."""
    if task is None or not task.attempts:
        return 0
    latest = set(task.attempts[-1].fingerprints)
    if not latest:
        return 0
    return max(sum(1 for a in task.attempts if fp in a.fingerprints) for fp in latest)


def progress_history(task: Task | None) -> list[ProgressVector]:
    """Recorded progress vectors of a task's attempts, oldest first."""
    return [a.progress for a in (task.attempts if task else []) if a.progress is not None]


def best_checkpoint(mission: Mission, current: ProgressVector | None) -> dict[str, Any] | None:
    """The checkpoint with the best recorded progress, if it is strictly better than ``current``."""
    if current is None:
        return None
    scored = [
        (badness(ProgressVector.model_validate(cp["progress"])), i, cp)
        for i, cp in enumerate(mission.checkpoints)
        if cp.get("progress")
    ]
    if not scored:
        return None
    # lowest badness; the latest checkpoint wins ties
    best = min(scored, key=lambda t: (t[0], -t[1]))
    return best[2] if best[0] < badness(current) else None


def environmental_repeats(mission: Mission, task_key: str) -> int:
    """Number of triage findings routed to the task that classify the failure as environmental."""
    return sum(
        1
        for f in mission.findings.values()
        if f.kind == "triage" and f.routed_to == task_key and f.payload.get("category") == "environmental"
    )


@dataclass(slots=True)
class _Evaluation:
    allowed: set[Action]
    #: action -> "guard: detail" for every action removed
    reasons: dict[Action, str] = field(default_factory=dict)
    #: set when a guard narrowed the choice to a small set (drives the replacement preference)
    restricted_by: str | None = None
    prefer_human: bool = False
    rollback_target: dict[str, Any] | None = None
    forced_rollback: bool = False


def _evaluate(
    mission: Mission, task_key: str, *, tournament_available: bool, counters: GuardCounters | None
) -> _Evaluation:
    lim = mission.budget.limits
    budget = effective_budget(mission, counters)
    task = mission.tasks.get(task_key)
    attempts = len(task.attempts) if task else 0
    repeats = fingerprint_repeats(task)
    history = progress_history(task)
    current = history[-1] if history else None
    target = best_checkpoint(mission, current)

    allowed = set(PREFERENCE)
    ev = _Evaluation(allowed=allowed)

    def drop(action: Action, why: str) -> None:
        if action in allowed:
            allowed.discard(action)
            ev.reasons[action] = why

    def restrict(keep: set[Action], why: str, *, human: bool = False) -> None:
        for a in list(allowed - keep):
            drop(a, why)
        ev.restricted_by = why
        ev.prefer_human = human

    # soft removals first
    if repeats >= 2:
        drop(Action.RETRY_SAME_AGENT, f"repeat_fingerprint_2: fingerprint seen {repeats}x on {task_key}")
    if budget.replans >= lim.max_replans:
        drop(Action.REPLAN, f"max_replans: {budget.replans} of {lim.max_replans} replans used")
    if not tournament_available:
        drop(Action.TOURNAMENT, "tournament_unavailable: no tournament engine/profile allows it")
    elif budget.tournaments >= lim.max_tournaments:
        drop(Action.TOURNAMENT, f"max_tournaments: {budget.tournaments} of {lim.max_tournaments} used")
    if target is None:
        drop(Action.ROLLBACK, "no_better_checkpoint: no earlier checkpoint beats the current progress")
    elif trend(history) == "worsening":
        ev.forced_rollback = True
    ev.rollback_target = target

    # hard narrowing, least to most severe; budget guards win over human-escalation guards
    if repeats >= 3:
        restrict(
            {Action.ASK_HUMAN, Action.STOP_PARTIAL},
            f"repeat_fingerprint_3: fingerprint seen {repeats}x",
            human=True,
        )
    if attempts >= lim.max_attempts_per_task:
        restrict(
            {Action.ASK_HUMAN, Action.STOP_PARTIAL},
            f"max_attempts: {attempts} of {lim.max_attempts_per_task} attempts used on {task_key}",
            human=True,
        )
    if environmental_repeats(mission, task_key) >= 2:
        restrict({Action.ASK_HUMAN}, "env_failure: environmental failure repeated", human=True)
    if budget.ratio() >= 1.0:
        restrict({Action.STOP_PARTIAL}, f"budget_exhausted: budget ratio {budget.ratio():.2f} >= 1")
    if budget.fix_cycles >= lim.max_fix_cycles:
        restrict({Action.STOP_PARTIAL}, f"max_fix_cycles: {budget.fix_cycles} of {lim.max_fix_cycles} used")
    if not allowed:  # defensive: STOP_PARTIAL is always a safe terminal
        allowed.add(Action.STOP_PARTIAL)
    return ev


def _estimate(mission: Mission, action: Action) -> tuple[int, int]:
    tokens, seconds = DEFAULT_COST[action]
    spec = COST_MODE.get(action)
    if spec is None:
        return tokens, seconds
    mode_id, times = spec
    subs = [s for s in mission.submissions.values() if s.mode_id == mode_id and s.usage]
    if subs:
        tokens = round(sum(sum(u.tokens_in + u.tokens_out for u in s.usage) for s in subs) / len(subs))
        seconds = round(sum(sum(u.latency_ms for u in s.usage) for s in subs) / len(subs) / 1000)
        seconds = max(seconds, 1)
    return tokens * times, seconds * times


def legal_actions(
    mission: Mission,
    task_key: str,
    *,
    tournament_available: bool,
    counters: GuardCounters | None = None,
) -> list[LegalAction]:
    """Actions the Shogun may choose for ``task_key`` right now, with deterministic cost estimates."""
    ev = _evaluate(mission, task_key, tournament_available=tournament_available, counters=counters)
    out: list[LegalAction] = []
    for action in PREFERENCE:
        if action not in ev.allowed:
            continue
        tokens, seconds = _estimate(mission, action)
        note = ""
        if action == Action.ROLLBACK and ev.rollback_target is not None:
            note = f"restore checkpoint {ev.rollback_target['sha']}"
            if ev.forced_rollback:
                note += " (progress is worsening)"
        if action == Action.STOP_PARTIAL and ev.restricted_by:
            note = ev.restricted_by
        out.append(
            LegalAction(
                action=action,
                target=task_key if action not in (Action.STOP_PARTIAL, Action.ABORT) else None,
                est_tokens=tokens,
                est_seconds=seconds,
                note=note,
            )
        )
    return out


def override(
    decision: Decision,
    mission: Mission,
    task_key: str,
    *,
    tournament_available: bool = False,
    counters: GuardCounters | None = None,
) -> tuple[Action, str | None]:
    """Validate the Shogun's choice against the guards.

    Returns ``(final_action, reason)``; ``reason`` is ``None`` when the choice stands, otherwise a
    ``"guard_name: detail"`` string. Replacement order: a human when a guard demands one, then the
    Shogun's own ``fallback_if_fails`` if legal, then ``PREFERENCE``.
    """
    ev = _evaluate(mission, task_key, tournament_available=tournament_available, counters=counters)
    chosen = decision.action
    if chosen in ev.allowed:
        if ev.forced_rollback and chosen in RETRY_LIKE and Action.ROLLBACK in ev.allowed:
            return Action.ROLLBACK, "progress_worsening: restoring the best checkpoint before retrying"
        return chosen, None
    # a hard narrowing (repeat x3, budget...) is the real reason even if a softer rule also removed the action
    reason = (
        ev.restricted_by
        or ev.reasons.get(chosen)
        or f"not_in_legal_set: {chosen.value} is not a valid decision here"
    )
    if ev.prefer_human and Action.ASK_HUMAN in ev.allowed:
        return Action.ASK_HUMAN, reason
    if decision.fallback_if_fails in ev.allowed:
        return decision.fallback_if_fails, reason
    for action in PREFERENCE:
        if action in ev.allowed:
            return action, reason
    return Action.STOP_PARTIAL, reason  # pragma: no cover - ``_evaluate`` never returns an empty set
