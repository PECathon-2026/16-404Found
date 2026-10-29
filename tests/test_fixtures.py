"""Tests asserting the baseline conditions and integrity of all evaluation fixtures (FX1-FX5)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

FIXTURES_DIR = Path("fixtures")


def test_all_fixtures_present() -> None:
    """Ensure all required fixture directories exist."""
    expected = [
        "fx1_feature_discounts",
        "fx2_bug_pagination",
        "fx3_red_test_recovery",
        "fx4_security_notes_api",
        "fx5_chaos/fx5a_ambiguous",
        "fx5_chaos/fx5b_tool_outage",
        "fx5_chaos/fx5c_contradiction",
    ]
    for rel in expected:
        p = FIXTURES_DIR / rel
        assert p.is_dir(), f"Expected fixture directory missing: {p}"
        assert (p / "scenario.toml").is_file(), f"scenario.toml missing in {p}"
        assert (p / "README.md").is_file(), f"README.md missing in {p}"
        assert (p / ".hidden" / "NOTES.md").is_file(), f".hidden/NOTES.md missing in {p}"


def test_scenario_toml_structures() -> None:
    """Validate scenario.toml schema across all fixtures."""
    for scen_file in FIXTURES_DIR.glob("**/scenario.toml"):
        with scen_file.open("rb") as f:
            data = tomllib.load(f)
        assert "id" in data
        assert "name" in data
        assert "request" in data
        assert "expect_outcome" in data
        assert "hidden_tests" in data
        assert isinstance(data["must_see_events"], list)


def test_planted_defects_not_in_visible_readme() -> None:
    """Planted defect notes must never leak into visible README files."""
    for readme in FIXTURES_DIR.glob("**/README.md"):
        content = readme.read_text(encoding="utf-8").lower()
        assert "planted" not in content
        assert "cwe-" not in content
        assert "vulnerability" not in content
        assert "defect" not in content


def test_fx1_baseline_and_hidden(pytestconfig: pytest.Config) -> None:
    """FX1 visible tests must be all green; hidden tests must fail on baseline code."""
    import subprocess
    fx1_dir = FIXTURES_DIR / "fx1_feature_discounts"

    # Visible tests pass
    res_vis = subprocess.run(["python", "-m", "pytest", "tests", "-q"], cwd=fx1_dir, capture_output=True, text=True)
    assert res_vis.returncode == 0
    assert "10 passed" in res_vis.stdout

    # Hidden tests fail on unfixed code
    res_hid = subprocess.run(["python", "-m", "pytest", ".hidden", "-q"], cwd=fx1_dir, capture_output=True, text=True)
    assert res_hid.returncode != 0
    assert "failed" in res_hid.stdout


def test_fx2_baseline_and_hidden() -> None:
    """FX2 visible tests must be green; hidden tests must fail on remainder cases."""
    import subprocess
    fx2_dir = FIXTURES_DIR / "fx2_bug_pagination"

    res_vis = subprocess.run(["python", "-m", "pytest", "tests", "-q"], cwd=fx2_dir, capture_output=True, text=True)
    assert res_vis.returncode == 0
    assert "6 passed" in res_vis.stdout

    res_hid = subprocess.run(["python", "-m", "pytest", ".hidden", "-q"], cwd=fx2_dir, capture_output=True, text=True)
    assert res_hid.returncode != 0
    assert "failed" in res_hid.stdout


def test_fx3_baseline_exactly_two_red() -> None:
    """FX3 baseline must have exactly 2 red tests (multiple spaces, newlines)."""
    import subprocess
    fx3_dir = FIXTURES_DIR / "fx3_red_test_recovery"

    res_vis = subprocess.run(["python", "-m", "pytest", "tests", "-q"], cwd=fx3_dir, capture_output=True, text=True)
    assert res_vis.returncode != 0
    assert "2 failed, 4 passed" in res_vis.stdout


def test_fx4_baseline_and_planted_vulnerabilities() -> None:
    """FX4 visible tests pass, hidden tests fail, and 3 planted issues are confirmed in source."""
    import subprocess
    fx4_dir = FIXTURES_DIR / "fx4_security_notes_api"

    res_vis = subprocess.run(["python", "-m", "pytest", "tests", "-q"], cwd=fx4_dir, capture_output=True, text=True)
    assert res_vis.returncode == 0
    assert "3 passed" in res_vis.stdout

    res_hid = subprocess.run(["python", "-m", "pytest", ".hidden", "-q"], cwd=fx4_dir, capture_output=True, text=True)
    assert res_hid.returncode != 0

    # Verify planted issues exist in code
    notes_code = (fx4_dir / "notes_api" / "notes.py").read_text(encoding="utf-8")
    assert "f\"SELECT id, title, content FROM notes WHERE content LIKE '%{term}%'\"" in notes_code
    assert "shell=True" in notes_code

    config_code = (fx4_dir / "notes_api" / "config.py").read_text(encoding="utf-8")
    assert "sk-live-" in config_code


def test_fx5_chaos_subfixtures() -> None:
    """FX5 sub-fixtures contain required answers.json and chaos configs."""
    fx5 = FIXTURES_DIR / "fx5_chaos"
    assert (fx5 / "fx5a_ambiguous" / "answers.json").is_file()
    assert (fx5 / "fx5c_contradiction" / "answers.json").is_file()

    with (fx5 / "fx5b_tool_outage" / "scenario.toml").open("rb") as f:
        data = tomllib.load(f)
    assert "disable_tools" in data.get("chaos", {})
