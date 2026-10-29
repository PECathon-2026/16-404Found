"""Configuration loading and management for DevPilot.

Reads configuration from `devpilot.toml` (with fallback to `devpilot.example.toml`
or built-in defaults) and supports environment variable overrides prefixed with
`DEVPILOT_`. Secrets such as `ANTHROPIC_API_KEY` are read strictly from the
environment and are never logged or stored in configuration files.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from devpilot.core.models import AgentRole, Budgets, ModelTier


class StrictConfig(BaseModel):
    """Base configuration model forbidding unexpected extra attributes."""

    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


class ModelsConfig(StrictConfig):
    """Models configured per tier and per agent role."""

    # Tiers
    frontier: str = "claude-opus-5-5"
    workhorse: str = "claude-sonnet-5-5"
    fast: str = "claude-haiku-5-5"

    # Agent roles
    shogun: str = "claude-opus-5-5"
    verifier: str = "claude-opus-5-5"
    scout: str = "claude-sonnet-5-5"
    samurai: str = "claude-sonnet-5-5"
    sentinel: str = "claude-sonnet-5-5"
    reviewer: str = "claude-sonnet-5-5"
    security: str = "claude-sonnet-5-5"

    def resolve_tier(self, tier: ModelTier) -> str:
        """Resolve a model identifier for a given ModelTier."""
        if tier == ModelTier.FRONTIER:
            return self.frontier
        if tier == ModelTier.WORKHORSE:
            return self.workhorse
        if tier == ModelTier.FAST:
            return self.fast
        return self.workhorse

    def resolve_agent(self, role: AgentRole) -> str:
        """Resolve a model identifier for an agent role."""
        mapping: dict[AgentRole, str] = {
            AgentRole.SHOGUN: self.shogun,
            AgentRole.VERIFIER: self.verifier,
            AgentRole.SCOUT: self.scout,
            AgentRole.SAMURAI: self.samurai,
            AgentRole.SENTINEL: self.sentinel,
            AgentRole.REVIEWER: self.reviewer,
            AgentRole.SECURITY: self.security,
            AgentRole.SOLO: self.workhorse,
        }
        return mapping.get(role, self.workhorse)


class SandboxConfig(StrictConfig):
    """Execution sandbox settings."""

    tier: Literal["auto", "worktree", "docker"] = "auto"


class GatesConfig(StrictConfig):
    """Human approval gates configuration."""

    apply: bool = True
    plan: bool = False
    command: bool = True
    clarification: bool = True
    escalation: bool = True


class ChaosConfig(StrictConfig):
    """Chaos engineering settings for testing resiliency and evaluation."""

    disable_tools: list[str] = Field(default_factory=list)
    chaos_test_timeout: bool = False
    answers: str = ""


class ProfileConfig(StrictConfig):
    """Behavioral profile customization."""

    description: str = ""
    allow_tournaments: bool = True
    allow_premortem: bool = True
    model_override: str | None = None
    plan_gate: bool = False
    tournament_min_risk: str = "high"


def _default_profiles() -> dict[str, ProfileConfig]:
    return {
        "fast": ProfileConfig(
            description="Fast execution: no tournaments, no premortem, sonnet everywhere",
            allow_tournaments=False,
            allow_premortem=False,
            model_override="claude-sonnet-5-5",
            plan_gate=False,
        ),
        "balanced": ProfileConfig(
            description="Balanced execution: standard cognitive modes and verification",
            allow_tournaments=True,
            allow_premortem=True,
            plan_gate=False,
        ),
        "careful": ProfileConfig(
            description="Careful execution: plan gate enabled, tournaments on medium risk",
            allow_tournaments=True,
            allow_premortem=True,
            plan_gate=True,
            tournament_min_risk="medium",
        ),
    }


class Settings(StrictConfig):
    """Global system configuration for DevPilot."""

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    budgets: Budgets = Field(default_factory=Budgets)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
    profiles: dict[str, ProfileConfig] = Field(default_factory=_default_profiles)
    active_profile: str = "balanced"

    def apply_profile(self, name: str) -> None:
        """Apply a named profile to adjust gates and execution parameters."""
        if name not in self.profiles:
            raise KeyError(f"Unknown profile: {name!r}; known: {sorted(self.profiles.keys())}")
        self.active_profile = name
        profile = self.profiles[name]
        self.gates.plan = profile.plan_gate
        if profile.model_override:
            self.models.workhorse = profile.model_override
            self.models.frontier = profile.model_override


def get_anthropic_api_key() -> str | None:
    """Retrieve Anthropic API key strictly from the environment.

    Never logs or persists this value to avoid credential leakage.
    """
    return os.environ.get("ANTHROPIC_API_KEY")


def _apply_env_overrides(data: dict[str, Any]) -> None:
    """Apply environment variable overrides starting with DEVPILOT_."""
    prefix = "DEVPILOT_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix):].lower()

        # Handle specific known env overrides
        if suffix == "profile":
            data["active_profile"] = value
        elif suffix == "sandbox" or suffix == "sandbox_tier":
            data.setdefault("sandbox", {})["tier"] = value
        elif suffix == "disable_tools":
            # Can be comma-separated
            tools = [t.strip() for t in value.split(",") if t.strip()]
            data.setdefault("chaos", {})["disable_tools"] = tools
        elif suffix == "chaos_test_timeout":
            data.setdefault("chaos", {})["chaos_test_timeout"] = value.lower() in ("1", "true", "yes")
        elif suffix.startswith("models_"):
            model_key = suffix.split("models_", 1)[1]
            data.setdefault("models", {})[model_key] = value
        elif suffix.startswith("gates_"):
            gate_key = suffix.split("gates_", 1)[1]
            data.setdefault("gates", {})[gate_key] = value.lower() in ("1", "true", "yes")
        elif suffix.startswith("budgets_"):
            budget_key = suffix.split("budgets_", 1)[1]
            budgets_dict = data.setdefault("budgets", {})
            try:
                if "." in value:
                    budgets_dict[budget_key] = float(value)
                else:
                    budgets_dict[budget_key] = int(value)
            except ValueError:
                budgets_dict[budget_key] = value


def load_settings(path: Path | str | None = None) -> Settings:
    """Load Settings from TOML file with environment variable overrides.

    Resolution order:
    1. Explicit `path` passed to function.
    2. File specified in `DEVPILOT_CONFIG` env var.
    3. `devpilot.toml` in the current working directory.
    4. `devpilot.example.toml` in the current working directory.
    5. Default configuration.
    """
    config_data: dict[str, Any] = {}

    target_path: Path | None = None
    if path is not None:
        target_path = Path(path)
    elif "DEVPILOT_CONFIG" in os.environ:
        target_path = Path(os.environ["DEVPILOT_CONFIG"])
    elif Path("devpilot.toml").is_file():
        target_path = Path("devpilot.toml")
    elif Path("devpilot.example.toml").is_file():
        target_path = Path("devpilot.example.toml")

    if target_path and target_path.is_file():
        with target_path.open("rb") as f:
            config_data = tomllib.load(f)

    _apply_env_overrides(config_data)

    settings = Settings.model_validate(config_data)
    if settings.active_profile and settings.active_profile in settings.profiles:
        settings.apply_profile(settings.active_profile)

    return settings
