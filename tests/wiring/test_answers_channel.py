"""AnswersFileHumanChannel: scripted gates for eval runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devpilot.core.models import ClarifyingOption, HumanPrompt
from devpilot.human import AnswersFileError, AnswersFileHumanChannel


def prompt(gate: str, pid: str, *keys: str) -> HumanPrompt:
    return HumanPrompt(
        id=pid,
        gate=gate,  # type: ignore[arg-type]
        title="t",
        body_md="b",
        options=[ClarifyingOption(key=k, label=k, consequence="c") for k in keys],
    )


def write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "answers.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


async def test_answers_by_gate_and_source(tmp_path: Path) -> None:
    ch = AnswersFileHumanChannel(
        write(tmp_path, {"clarification": "show", "escalation": "try ceiling division", "apply": "approve"})
    )
    d1 = await ch.ask(prompt("clarification", "P-1", "show", "hide"))
    assert (d1.choice, d1.free_text, d1.source, d1.prompt_id) == ("show", None, "answers_file", "P-1")
    d2 = await ch.ask(prompt("escalation", "P-2", "guidance", "accept_partial", "abort"))
    assert (d2.choice, d2.free_text) == (None, "try ceiling division")
    d3 = await ch.ask(prompt("apply", "P-3", "approve", "reject"))
    assert d3.choice == "approve" and d3.source == "answers_file"


async def test_object_and_list_answers(tmp_path: Path) -> None:
    ch = AnswersFileHumanChannel(
        write(tmp_path, {"apply": ["request_changes", {"choice": "approve", "free_text": "ok"}]})
    )
    opts = ("approve", "request_changes", "reject")
    assert (await ch.ask(prompt("apply", "P-1", *opts))).choice == "request_changes"
    d = await ch.ask(prompt("apply", "P-2", *opts))
    assert (d.choice, d.free_text) == ("approve", "ok")
    assert (await ch.ask(prompt("apply", "P-3", *opts))).choice == "approve"  # last repeats


async def test_missing_gate_never_approves(tmp_path: Path) -> None:
    ch = AnswersFileHumanChannel(write(tmp_path, {}))
    assert (await ch.ask(prompt("apply", "P-1", "approve", "reject"))).choice == "reject"
    esc = await ch.ask(prompt("escalation", "P-2", "guidance", "accept_partial", "abort"))
    assert esc.choice == "abort"
    assert (await ch.ask(prompt("clarification", "P-3", "a", "b"))).choice is None


def test_bad_files(tmp_path: Path) -> None:
    with pytest.raises(AnswersFileError):
        AnswersFileHumanChannel(tmp_path / "nope.json")
    with pytest.raises(AnswersFileError):
        AnswersFileHumanChannel(write(tmp_path, ["not", "an", "object"]))
