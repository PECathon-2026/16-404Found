"""ModeRuntime tests: scripted LLM, real event-sourced blackboard, fake gateway. No network."""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path

import pytest
from engine_helpers import (
    FakeGateway,
    cache_markers,
    make_change_report_payload,
    make_mission,
    make_rig,
)

from devpilot.core.events import EventType
from devpilot.core.models import ChangeReport, ModelTier, PreMortem
from devpilot.core.ports import ModeInvocation, ToolResult, ToolUse
from devpilot.engine import modes
from devpilot.engine.errors import (
    BudgetExceeded,
    ModeFailed,
    ModeRefused,
    StepBudgetExceeded,
)
from devpilot.llm import make_response
from devpilot.llm.history import assert_append_only

PREMORTEM = ModeInvocation("shogun.premortem", "shogun#1")
IMPLEMENT = ModeInvocation("samurai.implement", "samurai#1", task_key="T1", attempt=1)
GOOD_PM = {"risks": []}


def submit(payload: dict, name: str = "submit_premortem", tid: str = "s1"):  # type: ignore[no-untyped-def]
    return make_response(tool_uses=[ToolUse(tid, name, payload)])


def call(name: str, tid: str, **args: object):  # type: ignore[no-untyped-def]
    return ToolUse(tid, name, dict(args))


async def test_happy_path_tool_then_submit(tmp_path: Path) -> None:
    rig = await make_rig(
        tmp_path,
        [
            make_response(
                "looking", tool_uses=[call("fs_read", "t1", path="a.py")], thinking_summary="think"
            ),
            submit(GOOD_PM),
        ],
    )
    out = await rig.rt.invoke(PREMORTEM)
    assert isinstance(out, PreMortem)
    assert [c[0] for c in rig.gw.calls] == ["fs_read"]
    ctx = rig.gw.calls[0][2]
    assert ctx.allowed_tools == frozenset(modes.get("shogun.premortem").tools)
    assert ctx.workspace_ref == "main" and ctx.agent_id == "shogun#1"

    subs = [s for s in rig.bb.mission.submissions.values() if s.output_type == "PreMortem"]
    assert len(subs) == 1
    s = subs[0]
    assert s.id.startswith("S-") and len(s.id) == 10 and s.mode_id == "shogun.premortem"
    assert len(s.usage) == 2 and s.thinking_summary == "think"
    # budget was charged from LLM_TURN events through the projector
    assert rig.bb.mission.budget.tokens_in == 20

    # tool_result is fenced as untrusted and sits in the second request's last user message
    last = rig.llm.snapshots[1][-1]
    assert last["role"] == "user"
    block = last["content"][0]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "t1" and block["is_error"] is False
    assert block["content"].startswith('<untrusted source="tool:fs.read">')


async def test_event_ordering_and_started_payload(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [make_response("hm", tool_uses=[call("fs_read", "t1")]), submit(GOOD_PM)])
    await rig.rt.invoke(PREMORTEM)
    events = await rig.events()
    types = [e.type for e in events]
    i_start = types.index(EventType.MODE_STARTED)
    i_turns = [i for i, t in enumerate(types) if t == EventType.LLM_TURN]
    i_sub = types.index(EventType.SUBMISSION)
    i_fin = types.index(EventType.MODE_FINISHED)
    assert i_start < i_turns[0] < i_turns[-1] < i_sub < i_fin
    assert len(i_turns) == 2
    started = events[i_start]
    assert started.actor == "shogun#1" and started.mode_id == "shogun.premortem"
    p = started.payload
    assert p["mode"] == "shogun.premortem" and p["tier"] == "frontier" and p["thinking_budget"] == 8000
    assert "fs.read" in p["tools"] and "spec" in p["included"] and p["hidden"] == []
    assert set(p["token_estimates"]) == set(p["included"])
    turn = events[i_turns[0]].payload
    assert turn["stop_reason"] == "tool_use" and turn["text_excerpt"] == "hm" and "usage" in turn


async def test_text_deltas_are_ephemeral_events(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [submit(GOOD_PM)])
    seen: list[str] = []

    async def collect() -> None:
        async for ev in rig.store.subscribe(rig.bb.mission.id):
            seen.append(ev.type.value)
            if ev.type == EventType.MODE_FINISHED:
                return

    import asyncio

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)
    await rig.rt.invoke(PREMORTEM)
    await asyncio.wait_for(task, 2)
    assert "MODE_FINISHED" in seen
    assert "AGENT_TEXT_DELTA" not in await rig.types()  # never persisted


async def test_invalid_submit_then_valid(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [submit({"risks": "nope"}), submit(GOOD_PM, tid="s2")])
    out = await rig.rt.invoke(PREMORTEM)
    assert isinstance(out, PreMortem)
    err = rig.llm.snapshots[1][-1]["content"][0]
    assert err["is_error"] is True and err["tool_use_id"] == "s1"
    assert "risks" in err["content"] and "rejected" in err["content"]


async def test_semantic_validator_error_is_returned(tmp_path: Path) -> None:
    bad = make_change_report_payload(self_check_evidence_ids=["E-9999"])
    rig = await make_rig(
        tmp_path,
        [
            submit(bad, "submit_changereport"),
            submit(
                make_change_report_payload(self_check_evidence_ids=["E-0001"]), "submit_changereport", "s2"
            ),
        ],
    )
    out = await rig.rt.invoke(IMPLEMENT)
    assert isinstance(out, ChangeReport)
    assert "E-9999" in rig.llm.snapshots[1][-1]["content"][0]["content"]


async def test_repair_round_exhaustion(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [submit({"risks": 1}, tid=f"s{i}") for i in range(3)])
    with pytest.raises(ModeFailed) as ei:
        await rig.rt.invoke(PREMORTEM)  # max_repair_rounds=2 -> the third invalid submit fails
    assert ei.value.mode_id == "shogun.premortem" and "repair" in ei.value.reason
    types = await rig.types()
    assert types[-1] == "MODE_FAILED" and "SUBMISSION" not in types


async def test_end_turn_twice_then_fail_and_forcing_only_after_nudge(tmp_path: Path) -> None:
    rig = await make_rig(
        tmp_path, [make_response("done?"), make_response("really done"), make_response("no")]
    )
    with pytest.raises(ModeFailed):
        await rig.rt.invoke(PREMORTEM)
    reqs = rig.llm.requests
    assert len(reqs) == 3
    assert reqs[0].tool_choice is None
    forced = {"type": "tool", "name": "submit_premortem"}
    assert reqs[1].tool_choice == forced and reqs[2].tool_choice == forced
    # the instruction is permanently in history, appended (never replacing anything)
    instr = {"type": "text", "text": "You must now call the tool submit_premortem to submit your result."}
    final = rig.llm.snapshots[2]
    assert sum(1 for msg in final if msg["role"] == "user" and instr in msg["content"]) == 2
    assert_append_only(rig.llm.snapshots[0], rig.llm.snapshots[1])
    assert_append_only(rig.llm.snapshots[1], rig.llm.snapshots[2])
    assert (await rig.types())[-1] == "MODE_FAILED"


async def test_end_turn_then_submit_succeeds(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [make_response("hmm"), submit(GOOD_PM)])
    await rig.rt.invoke(PREMORTEM)
    assert rig.llm.requests[1].tool_choice == {"type": "tool", "name": "submit_premortem"}


async def test_instruction_added_once_for_forcing_models(tmp_path: Path) -> None:
    # Opus rejects forced tool_choice, so needs_submit_instruction is true; it must not double the nudge.
    rig = await make_rig(tmp_path, [make_response("x"), submit(GOOD_PM)], model="claude-opus-5-5")
    await rig.rt.invoke(PREMORTEM)
    texts = [
        b.get("text")
        for msg in rig.llm.snapshots[1]
        if msg["role"] == "user"
        for b in msg["content"]
        if isinstance(b, dict)
    ]
    assert sum(1 for t in texts if t and t.startswith("You must now call the tool")) == 1


async def test_parallel_reads_single_message_and_sequential_writes(tmp_path: Path) -> None:
    gw = FakeGateway(delays={"r1": 0.15, "r2": 0.15, "r3": 0.15, "w1": 0.05, "w2": 0.05})
    uses = [
        call("fs_read", "u1", tag="r1"),
        call("fs_read", "u2", tag="r2"),
        call("fs_edit", "u3", tag="w1"),
        call("fs_edit", "u4", tag="w2"),
        call("search_code", "u5", tag="r3"),
    ]
    rig = await make_rig(
        tmp_path,
        [
            make_response("", tool_uses=uses),
            submit(make_change_report_payload(), "submit_changereport"),
        ],
        gateway=gw,
    )
    await rig.rt.invoke(IMPLEMENT)

    # reads before the first write overlap
    assert gw.starts["r2"] < gw.ends["r1"] and gw.starts["r1"] < gw.ends["r2"]
    # writes never overlap each other or the reads around them, and keep the model's order
    assert gw.ends["r1"] <= gw.starts["w1"] and gw.ends["r2"] <= gw.starts["w1"]
    assert gw.ends["w1"] <= gw.starts["w2"] <= gw.ends["w2"] <= gw.starts["r3"]
    # one user message carrying all results in tool_use order
    msg = rig.llm.snapshots[1][-1]
    assert [b["tool_use_id"] for b in msg["content"]] == ["u1", "u2", "u3", "u4", "u5"]
    # write acknowledgements are not fenced; read output is
    assert msg["content"][2]["content"].startswith("{")
    assert msg["content"][0]["content"].startswith("<untrusted")


async def test_tool_failure_is_error_result_and_context_from_task(tmp_path: Path) -> None:
    gw = FakeGateway({"fs_read": ToolResult(False, "fs.read", "", error_code="NOPE", error_message="nope")})
    mission = make_mission()
    mission.tasks["T1"].may_edit_tests = True
    rig = await make_rig(
        tmp_path,
        [
            make_response("", tool_uses=[call("fs_read", "u1")]),
            submit(make_change_report_payload(), "submit_changereport"),
        ],
        gateway=gw,
        mission=mission,
    )
    await rig.rt.invoke(IMPLEMENT)
    assert rig.llm.snapshots[1][-1]["content"][0]["is_error"] is True
    ctx = gw.calls[0][2]
    assert ctx.may_edit_tests is True and ctx.file_locks == frozenset({"src/pager.py"})
    assert ctx.task_key == "T1"


async def test_refusal(tmp_path: Path) -> None:
    resp = make_response("", stop_reason="refusal")
    resp.raw_assistant_content = []
    rig = await make_rig(tmp_path, [resp])
    with pytest.raises(ModeRefused):
        await rig.rt.invoke(PREMORTEM)
    types = await rig.types()
    assert types[-1] == "MODE_FAILED" and types.count("LLM_TURN") == 1


async def test_max_tokens_continuation(tmp_path: Path) -> None:
    cut = make_response("partial", stop_reason="max_tokens")
    rig = await make_rig(tmp_path, [cut, submit(GOOD_PM)])
    await rig.rt.invoke(PREMORTEM)
    msgs = rig.llm.snapshots[1]
    assert msgs[1] == {"role": "assistant", "content": [{"type": "text", "text": "partial"}]}
    assert msgs[2] == {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": ("Your previous output was cut off by the length limit. Continue, more concisely."),
            }
        ],
    }


async def test_step_budget_exhausted(tmp_path: Path) -> None:
    tiny = dataclasses.replace(modes.get("shogun.premortem"), limits=modes.ModeLimits(max_steps=2))
    responses = [make_response("", tool_uses=[call("fs_read", f"t{i}")]) for i in range(5)]
    rig = await make_rig(tmp_path, responses, spec_lookup=lambda _: tiny)
    with pytest.raises(StepBudgetExceeded):
        await rig.rt.invoke(PREMORTEM)
    assert len(rig.llm.requests) == 2
    assert (await rig.types())[-1] == "MODE_FAILED"


async def test_mission_budget_exhausted(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [submit(GOOD_PM)])
    rig.bb.mission.budget.cost_usd = rig.bb.mission.budget.limits.max_cost_usd
    with pytest.raises(BudgetExceeded):
        await rig.rt.invoke(PREMORTEM)
    assert rig.llm.requests == []
    types = await rig.types()
    assert "BUDGET_EXCEEDED" in types and types[-1] == "MODE_FAILED"


async def test_wall_clock(tmp_path: Path) -> None:
    import asyncio

    spec = dataclasses.replace(modes.get("shogun.premortem"), limits=modes.ModeLimits(wall_clock_s=0))
    rig = await make_rig(tmp_path, [submit(GOOD_PM)], spec_lookup=lambda _: spec)

    async def slow(_req):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)

    rig.llm.complete = slow  # type: ignore[method-assign]
    with pytest.raises(ModeFailed, match="wall clock"):
        await rig.rt.invoke(PREMORTEM)


async def test_model_escalation_on_attempt_three(tmp_path: Path) -> None:
    payload = make_change_report_payload(differs_from_previous="now using ceil")
    rig = await make_rig(tmp_path, [submit(payload, "submit_changereport")])
    inv = ModeInvocation("samurai.rework", "samurai#1", task_key="T1", attempt=3)
    await rig.rt.invoke(inv)
    req = rig.llm.requests[0]
    assert req.tier == ModelTier.FRONTIER and req.thinking_budget == 16000
    events = await rig.events()
    esc = [e for e in events if e.type == EventType.MODEL_ESCALATED]
    assert len(esc) == 1 and esc[0].payload["to_tier"] == "frontier" and esc[0].payload["attempt"] == 3
    started = next(e for e in events if e.type == EventType.MODE_STARTED)
    assert started.payload["tier"] == "frontier" and events.index(esc[0]) < events.index(started)


async def test_no_escalation_before_threshold_and_override_wins(tmp_path: Path) -> None:
    payload = make_change_report_payload(differs_from_previous="x")
    rig = await make_rig(tmp_path, [submit(payload, "submit_changereport")])
    await rig.rt.invoke(ModeInvocation("samurai.rework", "s#1", task_key="T1", attempt=2))
    assert rig.llm.requests[0].tier == ModelTier.WORKHORSE
    assert "MODEL_ESCALATED" not in await rig.types()

    rig2 = await make_rig(tmp_path / "b", [submit(payload, "submit_changereport")])
    inv = ModeInvocation("samurai.rework", "s#1", task_key="T1", attempt=3, tier_override=ModelTier.FAST)
    await rig2.rt.invoke(inv)
    assert rig2.llm.requests[0].tier == ModelTier.FAST
    assert "MODEL_ESCALATED" not in await rig2.types()


async def test_rework_requires_difference_statement(tmp_path: Path) -> None:
    rig = await make_rig(
        tmp_path,
        [
            submit(make_change_report_payload(), "submit_changereport"),
            submit(make_change_report_payload(differs_from_previous="ceil"), "submit_changereport", "s2"),
        ],
    )
    await rig.rt.invoke(ModeInvocation("samurai.rework", "s#1", task_key="T1", attempt=2))
    assert "differs_from_previous" in rig.llm.snapshots[1][-1]["content"][0]["content"]


async def test_append_only_across_five_turns(tmp_path: Path) -> None:
    responses = [
        make_response("a", tool_uses=[call("fs_read", "t1")], thinking_summary="s1"),
        make_response("b"),  # end_turn -> nudge
        make_response("c", tool_uses=[call("fs_read", "t2"), call("search_code", "t3")]),
        submit({"risks": 3}, tid="bad"),
        submit(GOOD_PM, tid="ok"),
    ]
    responses[0].raw_assistant_content.insert(0, {"type": "thinking", "thinking": "hm", "signature": "sig"})
    rig = await make_rig(tmp_path, responses, debug=True)
    await rig.rt.invoke(PREMORTEM)
    snaps = rig.llm.snapshots
    assert len(snaps) == 5
    for prev, new in itertools.pairwise(snaps):
        assert_append_only(prev, new)
        assert len(new) > len(prev)
    # the assistant message with the thinking block is replayed verbatim
    assert snaps[4][1]["content"][0] == {"type": "thinking", "thinking": "hm", "signature": "sig"}


async def test_debug_mode_catches_history_edits(tmp_path: Path) -> None:
    from devpilot.llm.history import HistoryEditedError

    rig = await make_rig(tmp_path, [make_response("", tool_uses=[call("fs_read", "t1")]), submit(GOOD_PM)])
    orig = rig.rt._turn

    async def tamper(run):  # type: ignore[no-untyped-def]
        if run.messages and len(run.messages) > 1:
            run.messages[0] = {"role": "user", "content": [{"type": "text", "text": "edited"}]}
        return await orig(run)

    rig.rt._turn = tamper  # type: ignore[method-assign]
    with pytest.raises(HistoryEditedError):
        await rig.rt.invoke(PREMORTEM)


async def test_cache_breakpoints_at_most_four(tmp_path: Path) -> None:
    rig = await make_rig(
        tmp_path,
        [
            make_response("a", tool_uses=[call("fs_read", "t1")]),
            make_response("b"),
            submit(GOOD_PM),
        ],
    )
    await rig.rt.invoke(PREMORTEM)
    assert rig.llm.requests
    for req in rig.llm.requests:
        assert cache_markers(req) == 3
        assert [t.cache for t in req.tools].count(True) == 1 and req.tools[-1].cache
        assert req.tools[-1].name == "submit_premortem"
        assert [s.cache for s in req.system] == [False, True]
        assert req.system[0].text == "CONSTITUTION" and req.system[1].text == "PROMPT for shogun.premortem"
    first = rig.llm.snapshots[0][0]["content"]
    assert "cache_control" in first[0] and all("cache_control" not in b for b in first[1:])


async def test_submit_schema_and_metadata(tmp_path: Path) -> None:
    rig = await make_rig(tmp_path, [submit(GOOD_PM)])
    await rig.rt.invoke(PREMORTEM)
    req = rig.llm.requests[0]
    tool = req.tools[-1]
    assert tool.input_schema == PreMortem.model_json_schema()
    assert req.metadata["mode"] == "shogun.premortem" and req.max_output_tokens == 8000
    assert req.thinking_budget == 8000 and req.tier == ModelTier.FRONTIER


async def test_streamed_deltas_are_batched(tmp_path: Path) -> None:
    from devpilot.core.ports import LLMRequest

    rig = await make_rig(tmp_path, [submit(GOOD_PM)])
    final = make_response("x" * 500, tool_uses=[ToolUse("s1", "submit_premortem", GOOD_PM)])

    async def stream(req: LLMRequest):  # type: ignore[no-untyped-def]
        for _ in range(500):
            yield "x"
        yield final

    rig.llm.stream = stream  # type: ignore[method-assign]
    got: list[str] = []
    orig = rig.bb.emit

    async def spy(type_, actor, payload, **kw):  # type: ignore[no-untyped-def]
        if type_ == EventType.AGENT_TEXT_DELTA:
            got.append(payload["delta"])
        return await orig(type_, actor, payload, **kw)

    rig.bb.emit = spy  # type: ignore[method-assign]
    await rig.rt.invoke(PREMORTEM)
    assert "".join(got) == "x" * 500
    assert len(got) < 500
