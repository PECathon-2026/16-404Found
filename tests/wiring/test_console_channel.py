"""ConsoleHumanChannel with scripted keyboard input: never approves by accident."""

from __future__ import annotations

import io
from collections.abc import Iterator

from rich.console import Console

from devpilot.core import models as m
from devpilot.human import ConsoleHumanChannel


class Keys:
    def __init__(self, *lines: str) -> None:
        self.it: Iterator[str] = iter(lines)

    def __call__(self, label: str) -> str:
        try:
            return next(self.it)
        except StopIteration:
            raise EOFError from None


def channel(keys: Keys) -> tuple[ConsoleHumanChannel, io.StringIO]:
    buf = io.StringIO()
    con = Console(file=buf, width=100, force_terminal=False, legacy_windows=False)
    return ConsoleHumanChannel(con, input_fn=keys), buf


def apply_prompt() -> m.HumanPrompt:
    return m.HumanPrompt(
        id="P-9",
        gate="apply",
        title="Apply?",
        body_md="**Files:** a.py",
        options=[
            m.ClarifyingOption(key="approve", label="Approve", consequence="c"),
            m.ClarifyingOption(key="reject", label="Reject", consequence="c"),
        ],
    )


class FakeBB:
    def __init__(self, status: m.ACStatus) -> None:
        ac = m.AcceptanceCriterion(
            id="AC-1",
            given="g",
            when="w",
            then="t",
            verification_methods=[m.VerificationMethod.ACCEPTANCE_TEST],
        )
        self.mission = m.Mission(
            id="M-20260101-000000-ab12", request="r", repo_path="/r", workspace_path="/w"
        )
        self.mission.acs = [m.ACState(ac=ac, status=status, confidence=0.9)]


class FakeWS:
    async def diff(self, ref: str = "main", against: str = "baseline") -> str:
        return "diff --git a/a.py b/a.py\n+new line"


async def test_clarification_numbered_and_free_text() -> None:
    p = m.HumanPrompt(
        id="P-1",
        gate="clarification",
        title="?",
        body_md="q",
        options=[
            m.ClarifyingOption(key="show", label="Show", consequence="c"),
            m.ClarifyingOption(key="hide", label="Hide", consequence="c"),
        ],
    )
    ch, _ = channel(Keys("2"))
    d = await ch.ask(p)
    assert (d.choice, d.source) == ("hide", "cli")
    ch, _ = channel(Keys("", "keep them but dim"))  # empty answer is re-asked
    d = await ch.ask(p)
    assert (d.choice, d.free_text) == (None, "keep them but dim")


async def test_escalation_guidance_asks_for_text() -> None:
    p = m.HumanPrompt(
        id="P-2",
        gate="escalation",
        title="?",
        body_md="q",
        options=[
            m.ClarifyingOption(key="guidance", label="g", consequence="c"),
            m.ClarifyingOption(key="accept_partial", label="p", consequence="c"),
            m.ClarifyingOption(key="abort", label="a", consequence="c"),
        ],
    )
    ch, _ = channel(Keys("1", "use ceil"))
    d = await ch.ask(p)
    assert (d.choice, d.free_text) == ("guidance", "use ceil")
    ch, _ = channel(Keys("3"))
    assert (await ch.ask(p)).choice == "abort"


async def test_apply_requires_literal_approve_and_shows_diff() -> None:
    ch, out = channel(Keys("yes", "ok", "d", "approve"))
    ch.attach(FakeWS(), FakeBB(m.ACStatus.VERIFIED))  # type: ignore[arg-type]
    d = await ch.ask(apply_prompt())
    assert d.choice == "approve"
    assert "+new line" in out.getvalue() and "AC-1" in out.getvalue()


async def test_apply_unverified_must_ac_needs_short_id() -> None:
    ch, _ = channel(Keys("approve", "wrong", "approve", "ab12"))
    ch.attach(FakeWS(), FakeBB(m.ACStatus.FAILED))  # type: ignore[arg-type]
    d = await ch.ask(apply_prompt())
    assert d.choice == "approve"


async def test_apply_unverified_wrong_id_then_eof_rejects() -> None:
    ch, _ = channel(Keys("approve", "wrong"))
    ch.attach(FakeWS(), FakeBB(m.ACStatus.FAILED))  # type: ignore[arg-type]
    assert (await ch.ask(apply_prompt())).choice == "reject"


async def test_apply_eof_is_reject_never_approve() -> None:
    ch, _ = channel(Keys())
    assert (await ch.ask(apply_prompt())).choice == "reject"


async def test_apply_request_changes() -> None:
    ch, _ = channel(Keys("c", "handle empty input"))
    d = await ch.ask(apply_prompt())
    assert (d.choice, d.free_text) == ("request_changes", "handle empty input")
