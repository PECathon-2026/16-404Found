"""Integration smoke test: every mode runs end to end through the real runtime with its real prompt.

The scripted model submits the JSON example from the mode's own prompt file. This proves that
prompts, mode registry, runtime, context assembly, submit-tool schema and semantic validators
agree with each other — the seams between C02, C03 and C04.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from devpilot.core import models as m
from devpilot.core.ports import ModeInvocation, ToolUse
from devpilot.engine.modes import REGISTRY
from devpilot.llm.fake import make_response
from devpilot.prompts import load_constitution, load_mode_prompt
from tests.engine.engine_helpers import make_evidence, make_mission, make_rig

JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
EVIDENCE_ID = re.compile(r"\bE-\d{4,}\b")


def _example(mode_id: str) -> dict[str, Any]:
    match = JSON_BLOCK.search(load_mode_prompt(mode_id))
    assert match, f"{mode_id}: no json example"
    return json.loads(match.group(1))


def _extra_context(mode_id: str, example: dict[str, Any]) -> dict[str, Any]:
    if mode_id == "shogun.decide":
        dossier = m.DecisionDossier(
            trigger_event_seq=1, trigger_summary="tests red", evidence_summaries={},
            task_histories={}, progress={}, budget=m.BudgetState(),
            legal_actions=[m.LegalAction(action=m.Action(example["action"]), target=example.get("target"),
                                         est_tokens=1000, est_seconds=10)],
            open_findings=[],
        )
        return {"dossier": dossier.model_dump(mode="json")}
    if mode_id == "judge.select":
        score = m.CandidateScore(candidate=example["winner"], gates_passed=True, gate_failures=[],
                                 public_pass_rate=1.0, regressions=0, mutation_kill_rate=0.8, lint_issues=0,
                                 diff_lines=6, convention_similarity=0.9, weighted=0.9)
        return {"candidate_scores": [score.model_dump(mode="json")]}
    if mode_id == "reviewer.review":
        return {"lens": example.get("lens", "correctness")}
    if mode_id == "samurai.explore":
        return {"strategy_hint": "fix at the call site"}
    if mode_id == "scout.investigate":
        return {"question": example.get("question", "why does the last page drop items?")}
    return {}


def _align_mission(mode_id: str, mission: m.Mission, example: dict[str, Any]) -> None:
    """Make the fixture mission consistent with the prompt's example, so validators judge the example
    against a world in which it is true (they correctly reject it otherwise)."""
    if mode_id == "shogun.plan":
        mission.plans = []  # the example is a first plan, not a revision
    if mode_id == "verifier.verify":
        mission.acs = [m.ACState(ac=m.AcceptanceCriterion(
            id=v["ac_id"], given="g", when="w", then="t", verification_methods=["probe"],
            preserves_existing_behaviour=(i == 0))) for i, v in enumerate(example["per_ac"])]
        if mission.spec is not None:  # the spec is the source of truth for AC ids
            mission.spec.acceptance_criteria = [s.ac for s in mission.acs]
    if mode_id == "sentinel.triage":
        cases = [m.TestCaseResult(nodeid=item["nodeid"], outcome=m.TestOutcome.FAILED,
                                  baseline_outcome=m.TestOutcome.PASSED, classification=m.TestClass.NEW_FAIL,
                                  fingerprint=item["fingerprint"]) for item in example["items"]]
        mission.test_runs.append(m.TestRun(id="TR-smoke", evidence_id="E-0001", scope="full",
                                           workspace_ref="main", totals={"failed": len(cases)},
                                           cases=cases, regressions=[], verdict="red"))


@pytest.mark.parametrize("mode_id", sorted(REGISTRY))
async def test_mode_runs_with_real_prompt(tmp_path: Path, mode_id: str) -> None:
    spec = REGISTRY[mode_id]
    example = _example(mode_id)
    mission = make_mission()
    for eid in sorted(set(EVIDENCE_ID.findall(json.dumps(example)))):
        mission.evidence[eid] = make_evidence(eid)
    _align_mission(mode_id, mission, example)

    submit = ToolUse(id="tu_submit", name=spec.submit_tool, input=example)
    rig = await make_rig(tmp_path, [make_response("Submitting.", tool_uses=[submit])], mission=mission)
    rig.rt._prompt_source = load_mode_prompt  # type: ignore[attr-defined]
    rig.rt._constitution = load_constitution  # type: ignore[attr-defined]

    task_key = "T1" if "T1" in mission.tasks else None
    inv = ModeInvocation(mode_id=mode_id, agent_id=f"{spec.agent.value}#1", task_key=task_key, attempt=1,
                         extra_context=_extra_context(mode_id, example))
    out = await rig.rt.invoke(inv)

    assert isinstance(out, spec.output)
    req = rig.llm.requests[0]
    system_text = "\n".join(b.text for b in req.system)
    assert "DevPilot Constitution" in system_text
    assert spec.submit_tool in system_text
    assert spec.submit_tool in {t.name for t in req.tools}
    types = await rig.types()
    assert types.index("MODE_STARTED") < types.index("SUBMISSION") < types.index("MODE_FINISHED")
