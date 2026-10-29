"""CLI commands via typer's CliRunner: no network, no API key."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from devpilot import wiring
from devpilot.cli import app, exit_code_for
from devpilot.core.events import Event, EventType
from devpilot.core.models import MissionStatus

runner = CliRunner()
FAKE_KEY = "sk-ant-api03-SUPERSECRETVALUE-1234567890"


def test_doctor_runs_and_never_prints_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert FAKE_KEY not in result.output and "SUPERSECRET" not in result.output
    assert "ANTHROPIC_API_KEY" in result.output and "set" in result.output
    for needle in ("python", "git", "docker", "tool registry", "test runner", "repo intel"):
        assert needle in result.output


def test_doctor_reports_missing_key_and_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        wiring,
        "probe_components",
        lambda: dict.fromkeys(("tool registry", "test runner", "repo intel", "delta debugger"), False),
    )
    result = runner.invoke(app, ["doctor"])
    assert "missing" in result.output
    assert "Fallbacks in effect" in result.output
    assert "TOOL_UNAVAILABLE" in result.output and "--allow-missing" in result.output


def test_modes_lists_the_registry() -> None:
    result = runner.invoke(app, ["modes"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    for needle in ("shogun.plan", "verifier.verify", "samurai.implement", "frontier", "hidden"):
        assert needle in result.output
    assert "change_report" in result.output  # the verifier's hidden slices


def write_events(runs: Path, mission_id: str) -> None:
    d = runs / mission_id
    d.mkdir(parents=True)
    evs = [
        Event(
            seq=1,
            mission_id=mission_id,
            type=EventType.MISSION_CREATED,
            actor="system",
            summary="Mission created",
        ),
        Event(
            seq=2, mission_id=mission_id, type=EventType.TOOL_CALL, actor="samurai#1", summary="Call fs.read"
        ),
        Event(seq=3, mission_id=mission_id, type=EventType.MISSION_FINISHED, actor="system", summary="done"),
    ]
    (d / "events.jsonl").write_bytes(b"".join(e.model_dump_json().encode() + b"\n" for e in evs))


def test_events_prints_and_filters(tmp_path: Path) -> None:
    write_events(tmp_path, "M-20260101-000000-ab12")
    result = runner.invoke(app, ["events", "M-20260101-000000-ab12", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Mission created" in result.output and "Call fs.read" in result.output and "done" in result.output
    only = runner.invoke(
        app, ["events", "M-20260101-000000-ab12", "--runs-dir", str(tmp_path), "--type", "tool_call"]
    )
    assert "Call fs.read" in only.output and "Mission created" not in only.output
    # --follow stops by itself once the mission has finished
    followed = runner.invoke(
        app, ["events", "M-20260101-000000-ab12", "--runs-dir", str(tmp_path), "--follow"]
    )
    assert followed.exit_code == 0 and "done" in followed.output


def test_events_errors(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["events", "M-nope", "--runs-dir", str(tmp_path)])
    assert missing.exit_code == 66
    write_events(tmp_path, "M-20260101-000000-ab12")
    bad = runner.invoke(
        app, ["events", "M-20260101-000000-ab12", "--runs-dir", str(tmp_path), "--type", "NOPE"]
    )
    assert bad.exit_code == 64


def test_run_refuses_without_test_runner(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        wiring,
        "probe_components",
        lambda: {"tool registry": False, "test runner": False, "repo intel": True, "delta debugger": True},
    )
    runs = tmp_path / "runs"
    result = runner.invoke(app, ["run", "--repo", str(git_repo), "--runs-dir", str(runs), "fix the bug"])
    assert result.exit_code == 69
    assert "no test runner" in result.output and "WP-G05" in result.output and "WP-G04" in result.output
    assert "--allow-missing" in result.output
    assert not runs.exists()  # nothing was created before refusing


def test_run_single_mode_is_not_wired(git_repo: Path) -> None:
    result = runner.invoke(app, ["run", "--repo", str(git_repo), "--mode", "single", "x"])
    assert result.exit_code == 64
    assert "single-agent baseline not yet wired (WP-G14)" in result.output


def test_run_rejects_bad_repo_and_mode(tmp_path: Path) -> None:
    assert runner.invoke(app, ["run", "--repo", str(tmp_path / "nope"), "x"]).exit_code == 66
    assert runner.invoke(app, ["run", "--mode", "wat", "x"]).exit_code == 64


def test_exit_codes() -> None:
    assert exit_code_for(MissionStatus.COMPLETED_VERIFIED) == 0
    assert exit_code_for(MissionStatus.COMPLETED_PARTIAL) == 2
    assert exit_code_for(MissionStatus.FAILED) == 3
    assert exit_code_for(MissionStatus.ABORTED) == 130
