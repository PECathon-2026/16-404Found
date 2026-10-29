from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VerificationSpec(BaseModel):
    method: Literal["test_selector", "command", "static_check", "manual_review"]
    selectors: list[str] = []          # test_selector: pytest paths / node ids (tests may be written by this mission)
    argv: list[str] = []               # command: run in the verifier sandbox (verify profile)
    expect_exit: int = 0
    path: str | None = None            # static_check
    must_match: str | None = None
    must_not_match: str | None = None
    rubric: str | None = None          # manual_review


class PlanCriterion(BaseModel):
    id: str
    text: str
    verification: VerificationSpec


class PlanTask(BaseModel):
    ref: str
    kind: Literal["IMPLEMENT", "WRITE_TESTS"]
    title: str
    description: str
    depends_on: list[str] = []
    criteria: list[str] = []
    files_hint: list[str] = []


class Ambiguity(BaseModel):
    question: str
    blocking: bool = False
    assumed_default: str | None = None


class PlanResult(BaseModel):
    objectives: list[str] = []
    acceptance_criteria: list[PlanCriterion] = []
    tasks: list[PlanTask] = []
    risks: list[str] = []
    ambiguities: list[Ambiguity] = []
    repo_notes: str = ""


class CritiqueResponse(BaseModel):
    """Developer's answer to a CRITIQUE. A DISPUTE must carry evidence (AGENTS.md §C); otherwise it is rejected."""
    finding_id: str
    stance: Literal["ACCEPT", "DISPUTE"]
    rationale: str
    evidence_refs: list[dict] = Field(default_factory=list)


class DeveloperResult(BaseModel):
    critique_responses: list[CritiqueResponse] = Field(default_factory=list)
    summary: str
    known_gaps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class SecurityReview(BaseModel):
    summary: str
    quality_notes: list[str] = Field(default_factory=list)
