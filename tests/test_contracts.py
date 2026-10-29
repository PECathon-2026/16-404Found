"""Tests validating core data models, mode specifications, and contracts.

Asserts:
- Every core model can be imported and inspected.
- Every registered ModeSpec output model produces a valid JSON schema.
- The Verifier's context recipe rigorously hides `change_report`.
- System settings load correctly from TOML and reflect profile/budget contracts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.config import Settings, get_anthropic_api_key, load_settings
from devpilot.core import events as ev
from devpilot.core import models as m
from devpilot.core import ports as p
from devpilot.engine import modes


def test_core_models_importable() -> None:
    """Every critical model, record, and enum must exist on devpilot.core.models."""
    assert issubclass(m.LLMOutput, m.Strict)
    assert issubclass(m.Record, m.Strict)
    assert hasattr(m, "Mission")
    assert hasattr(m, "Task")
    assert hasattr(m, "Plan")
    assert hasattr(m, "MissionSpec")
    assert hasattr(m, "AcceptanceCriterion")
    assert hasattr(m, "ChangeReport")
    assert hasattr(m, "TriageReport")
    assert hasattr(m, "VerifierVerdict")
    assert hasattr(m, "ReviewReport")
    assert hasattr(m, "SecurityReport")
    assert hasattr(m, "Decision")
    assert hasattr(m, "Budgets")
    assert hasattr(m, "BudgetState")
    assert hasattr(m, "Event") if hasattr(m, "Event") else hasattr(ev, "Event")
    assert hasattr(p, "ToolGateway")
    assert hasattr(p, "Workspaces")
    assert hasattr(p, "Executor")


def test_all_mode_outputs_generate_json_schema() -> None:
    """Every registered ModeSpec.output must be a Pydantic model generating a valid JSON schema."""
    assert len(modes.REGISTRY) >= 18, f"Expected at least 18 modes, found {len(modes.REGISTRY)}"
    for mode_id, spec in modes.REGISTRY.items():
        assert issubclass(spec.output, m.LLMOutput), f"Mode {mode_id} output does not inherit from LLMOutput"
        schema = spec.output.model_json_schema()
        assert isinstance(schema, dict), f"Mode {mode_id} failed to produce dict schema"
        assert "properties" in schema or "type" in schema, f"Invalid JSON schema for mode {mode_id}"


def test_verifier_context_recipe_hides_change_report() -> None:
    """The Verifier mode MUST enforce information hiding by excluding change_report."""
    verifier_spec = modes.get("verifier.verify")
    assert modes.Slice.CHANGE_REPORT in verifier_spec.context.hidden, (
        "Slice.CHANGE_REPORT must be declared in verifier.verify hidden slices"
    )
    assert modes.Slice.CHANGE_REPORT not in verifier_spec.context.slices, (
        "Slice.CHANGE_REPORT must not be present in verifier.verify context slices"
    )
    # Also verify reviewer hides change_report
    reviewer_spec = modes.get("reviewer.review")
    assert modes.Slice.CHANGE_REPORT in reviewer_spec.context.hidden
    assert modes.Slice.CHANGE_REPORT not in reviewer_spec.context.slices


def test_settings_load_from_example_toml(tmp_path: Path) -> None:
    """Settings can load from devpilot.example.toml and parse budgets, models, and profiles."""
    example_path = Path("devpilot.example.toml")
    assert example_path.exists(), "devpilot.example.toml must exist"
    settings = load_settings(example_path)

    assert settings.models.frontier == "claude-opus-5-5"
    assert settings.models.workhorse == "claude-sonnet-5-5"
    assert settings.models.fast == "claude-haiku-5-5"
    assert settings.budgets.max_attempts_per_task == 4
    assert settings.budgets.max_fix_cycles == 8
    assert settings.gates.apply is True

    # Test tier and agent resolution
    assert settings.models.resolve_tier(m.ModelTier.FRONTIER) == "claude-opus-5-5"
    assert settings.models.resolve_tier(m.ModelTier.WORKHORSE) == "claude-sonnet-5-5"
    assert settings.models.resolve_agent(m.AgentRole.SHOGUN) == "claude-opus-5-5"
    assert settings.models.resolve_agent(m.AgentRole.SAMURAI) == "claude-sonnet-5-5"


def test_settings_profile_application() -> None:
    """Applying a profile alters plan gates and model overrides properly."""
    settings = Settings()
    assert settings.gates.plan is False

    settings.apply_profile("careful")
    assert settings.active_profile == "careful"
    assert settings.gates.plan is True

    settings.apply_profile("fast")
    assert settings.active_profile == "fast"
    assert settings.gates.plan is False
    assert settings.models.workhorse == "claude-sonnet-5-5"


def test_settings_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables with DEVPILOT_ prefix override configuration values."""
    monkeypatch.setenv("DEVPILOT_MODELS_FRONTIER", "test-frontier-model")
    monkeypatch.setenv("DEVPILOT_DISABLE_TOOLS", "search.rg, scan.bandit")
    monkeypatch.setenv("DEVPILOT_BUDGETS_MAX_ATTEMPTS_PER_TASK", "7")
    monkeypatch.setenv("DEVPILOT_SANDBOX_TIER", "docker")

    settings = load_settings(path=Path("devpilot.example.toml"))
    assert settings.models.frontier == "test-frontier-model"
    assert settings.chaos.disable_tools == ["search.rg", "scan.bandit"]
    assert settings.budgets.max_attempts_per_task == 7
    assert settings.sandbox.tier == "docker"


def test_anthropic_api_key_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic API key is fetched only from environment and not exposed in Settings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret-123456789012345678")
    assert get_anthropic_api_key() == "sk-ant-test-secret-123456789012345678"

    settings = Settings()
    # Confirm it does not leak into settings representations
    assert "sk-ant-test-secret" not in repr(settings)
    assert "sk-ant-test-secret" not in str(settings)
