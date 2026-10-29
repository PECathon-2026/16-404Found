"""Prompt library tests: coverage of the registry, tool hygiene, and valid output examples."""

from __future__ import annotations

import json
import re

import pytest

from devpilot.engine.modes import REGISTRY, ModeSpec
from devpilot.prompts import MODES_DIR, load_constitution, load_mode_prompt

ALL_TOOLS = sorted({tool for spec in REGISTRY.values() for tool in spec.tools})
MODE_IDS = sorted(REGISTRY)


def _mentions(text: str, name: str) -> bool:
    # Lookarounds stop "fs.write" from matching inside "fs.write_probe".
    return re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", text) is not None


def test_every_mode_has_a_prompt_and_no_extras() -> None:
    on_disk = {p.stem for p in MODES_DIR.glob("*.md")}
    assert on_disk == set(REGISTRY)


def test_unknown_mode_raises_key_error() -> None:
    with pytest.raises(KeyError):
        load_mode_prompt("no.such.mode")
    with pytest.raises(KeyError):
        load_mode_prompt("../constitution")


def test_loaders_are_cached_and_nonempty() -> None:
    assert load_constitution() is load_constitution()
    assert load_mode_prompt("scout.recon") is load_mode_prompt("scout.recon")


@pytest.mark.parametrize("mode_id", MODE_IDS)
def test_prompt_has_required_sections_and_length(mode_id: str) -> None:
    text = load_mode_prompt(mode_id)
    for heading in (
        "## Role & objective",
        "## What you receive",
        "## How to work",
        "## Tools for this mode",
        "## Definition of done & output",
        "## Common failure modes to avoid",
    ):
        assert heading in text, f"{mode_id}: missing {heading}"
    assert 60 <= len(text.splitlines()) <= 160, mode_id


@pytest.mark.parametrize("mode_id", MODE_IDS)
def test_prompt_names_its_submit_tool(mode_id: str) -> None:
    spec = REGISTRY[mode_id]
    assert _mentions(load_mode_prompt(mode_id), spec.submit_tool)


@pytest.mark.parametrize("mode_id", MODE_IDS)
def test_prompt_lists_exactly_its_tools_and_no_others(mode_id: str) -> None:
    spec = REGISTRY[mode_id]
    text = load_mode_prompt(mode_id)
    for tool in spec.tools:
        assert _mentions(text, tool), f"{mode_id}: tool {tool} not described"
    for tool in ALL_TOOLS:
        if tool not in spec.tools:
            assert not _mentions(text, tool), f"{mode_id}: mentions foreign tool {tool}"


def _first_json_block(text: str) -> object:
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    assert match, "no ```json block"
    return json.loads(match.group(1))


@pytest.mark.parametrize("mode_id", MODE_IDS)
def test_json_example_validates_against_output_model(mode_id: str) -> None:
    spec: ModeSpec = REGISTRY[mode_id]
    spec.output.model_validate(_first_json_block(load_mode_prompt(mode_id)))


def test_constitution_is_stable_text() -> None:
    text = load_constitution()
    assert len(text.splitlines()) <= 120
    assert not re.search(r"\b(19|20)\d{2}\b", text)
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", text)
    assert "{{" not in text and "{%" not in text
    for needle in ("untrusted", "evidence", "rationale", "submit_"):
        assert needle in text


@pytest.mark.parametrize("mode_id", ["verifier.verify", "reviewer.review", "security.inspect"])
def test_independent_modes_state_reasoning_is_withheld(mode_id: str) -> None:
    text = load_mode_prompt(mode_id).lower()
    assert "withheld" in text
    assert "reasoning" in text


def test_no_unexpanded_placeholders_or_shouting() -> None:
    for mode_id in MODE_IDS:
        text = load_mode_prompt(mode_id)
        assert "{{" not in text, mode_id
        assert not re.search(r"\b(CRITICAL|MUST|NEVER|ALWAYS|IMPORTANT)\b", text), mode_id
