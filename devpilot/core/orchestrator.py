"""Orchestrator: the brain that routes between agents and enforces all rules."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from core.state import SharedState, RunStatus
from core.board import MessageBoard
from core.logger import RunLogger


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Orchestrator:
    """
    Routes between agents based on shared state.

    Implements the routing rules from PLAN.md section 4.
    """

    def __init__(
        self,
        repo_path: Path,
        request: str,
        simulate_missing: str | None = None,
    ):
        """Set up a new run: create workspace copy, initialize state and logger."""
        self.run_id = f"run_{uuid.uuid4().hex[:8]}"

        # Create workspace (temp copy of the repo)
        self.workspace_path = Path(tempfile.mkdtemp(prefix=f"devpilot_{self.run_id}_"))
        shutil.copytree(str(repo_path), str(self.workspace_path), dirs_exist_ok=True)

        # Initialize shared state
        self.state = SharedState(
            run_id=self.run_id,
            request=request,
            repo_path=str(repo_path),
            workspace_path=str(self.workspace_path),
            simulate_missing=simulate_missing,
        )

        self.board = MessageBoard()
        self.logger = RunLogger(self.run_id)
        self._step_count = 0
        self._max_global_steps = 50  # safety cap

        self.logger.log(
            "orchestrator",
            "RUN_START",
            input_summary=f"repo={repo_path}, request={request[:80]}",
        )

    def _is_ambiguous(self, request: str) -> bool:
        """Return True if the request has no specifics (very short or just keywords)."""
        words = request.strip().split()
        # Heuristic: fewer than 5 words, or contains only generic verbs without object details
        vague_phrases = {"add a discount", "fix the bug", "improve code", "add feature"}
        req_lower = request.strip().lower()
        if len(words) < 5:
            return True
        for phrase in vague_phrases:
            if req_lower == phrase:
                return True
        return False

    def _tasks_unfinished(self) -> bool:
        """Return True if any task is still pending or in progress."""
        return any(t.status in ("pending", "in_progress") for t in self.state.tasks)

    def _tests_run_since_last_edit(self) -> bool:
        """Return True if tests have been run after the last edit."""
        if not self.state.test_runs:
            return False
        if not self.state.last_edit_time:
            return True
        last_test = max(tr.timestamp for tr in self.state.test_runs)
        return last_test > self.state.last_edit_time

    def _all_criteria_met(self) -> bool:
        """Return True if all criteria have status=MET."""
        if not self.state.criteria:
            return False
        return all(c.status == "met" for c in self.state.criteria)

    def _review_done(self) -> bool:
        """Return True if the reviewer has run."""
        return self.board.has_type("REVIEW_ISSUE") or any(
            e.get("event_type") == "AGENT_COMPLETE" and e.get("agent") == "reviewer"
            for e in self.logger.read_all()
        )

    def _open_review_issues(self) -> bool:
        """Return True if any review issues are still open."""
        return any(i.status == "open" for i in self.state.review_issues)

    def _failed_tests(self) -> bool:
        """Return True if the latest test run failed."""
        if not self.state.test_runs:
            return False
        latest = max(self.state.test_runs, key=lambda tr: tr.timestamp)
        return latest.exit_code != 0

    def _unmet_criteria(self) -> bool:
        """Return True if verifier found unmet criteria."""
        return self.board.has_type("VERIFY_FINDING")

    def _escalate(self, reason: str) -> None:
        """Post ESCALATE and move to escalated state."""
        print(f"\n🚨 ESCALATE: {reason}")
        self.board.post("ESCALATE", "orchestrator", "human", {
            "reason": reason,
            "retries_used": self.state.retries,
            "test_runs": len(self.state.test_runs),
        })
        self.logger.log("orchestrator", "ESCALATE", output_summary=reason)
        self.state.status = RunStatus.ESCALATED

    def run(self) -> None:
        """Main orchestration loop."""
        state = self.state
        board = self.board
        logger = self.logger

        print(f"\n🚀 DevPilot Run: {self.run_id}")
        print(f"📁 Workspace: {self.workspace_path}")
        print(f"📝 Request: {state.request}\n")

        # Step 1: Check ambiguity
        if self._is_ambiguous(state.request):
            from agents.planner import PlannerAgent
            planner = PlannerAgent(state, board, logger)
            plan_set = planner.run()
            if not plan_set:
                # Clarify was posted
                if planner.clarify_question:
                    print(f"\n⚠️  Request is ambiguous. Waiting for clarification.")
                    state.status = RunStatus.STOPPED
                    return
            # If plan was set despite ambiguity, continue
        else:
            # Run planner
            from agents.planner import PlannerAgent
            planner = PlannerAgent(state, board, logger)
            plan_set = planner.run()
            if not plan_set:
                state.status = RunStatus.STOPPED
                return

        state.status = RunStatus.BUILDING
        print(f"📋 Plan: {len(state.criteria)} criteria, {len(state.tasks)} tasks")

        # Main orchestration loop
        while self._step_count < self._max_global_steps:
            self._step_count += 1

            # Check for PLAN_GAP - send to planner
            plan_gap_msgs = board.get_by_type("PLAN_GAP")
            if plan_gap_msgs:
                gap = plan_gap_msgs[-1]
                print(f"\n📌 PLAN_GAP detected - sending to Planner for revision...")
                from agents.planner import PlannerAgent
                revise_planner = PlannerAgent(state, board, logger)
                revise_planner.run(revision_context=gap.payload.get("description", ""))
                # Remove processed PLAN_GAP messages
                board._messages = [m for m in board._messages if m.type != "PLAN_GAP"]
                continue

            # Tasks unfinished -> Developer
            if self._tasks_unfinished():
                state.status = RunStatus.BUILDING
                state.last_edit_time = _now()
                print(f"\n👨‍💻 Developer running... (retry {state.retries}/{state.max_retries})")
                from agents.developer import DeveloperAgent
                dev = DeveloperAgent(state, board, logger)
                dev.run()
                continue

            # Tests not run since last edit -> Verifier
            if not self._tests_run_since_last_edit():
                state.status = RunStatus.VERIFYING
                print(f"\n🔍 Verifier running...")
                from agents.verifier import VerifierAgent
                verifier = VerifierAgent(state, board, logger)
                verifier.run()
                continue

            # Tests failed and retries < max -> Developer (with failure info)
            if self._failed_tests() and state.retries < state.max_retries:
                state.retries += 1
                state.status = RunStatus.BUILDING
                print(f"\n🔄 Test failure - Developer retry {state.retries}/{state.max_retries}")
                from agents.developer import DeveloperAgent
                dev = DeveloperAgent(state, board, logger)
                dev.run()
                # Reset verify time to force re-run
                state.last_verify_time = ""
                state.test_runs.clear()
                continue

            # Tests failed and retries exhausted -> ESCALATE
            if self._failed_tests() and state.retries >= state.max_retries:
                self._escalate(
                    f"Tests still failing after {state.max_retries} retries. "
                    f"Manual intervention needed."
                )
                break

            # Verifier found unmet criteria -> Developer
            if self._unmet_criteria() and state.retries < state.max_retries:
                state.retries += 1
                print(f"\n⚠️  Unmet criterion - Developer retry {state.retries}/{state.max_retries}")
                from agents.developer import DeveloperAgent
                dev = DeveloperAgent(state, board, logger)
                dev.run()
                state.test_runs.clear()
                state.last_edit_time = _now()
                continue

            # Review not done -> Reviewer
            if not self._review_done():
                state.status = RunStatus.REVIEWING
                print(f"\n🔎 Reviewer running...")
                from agents.reviewer import ReviewerAgent
                reviewer = ReviewerAgent(state, board, logger)
                reviewer.run()
                continue

            # Open review issues -> Developer
            if self._open_review_issues() and state.retries < state.max_retries:
                state.retries += 1
                print(f"\n🔧 Review issues - Developer retry {state.retries}/{state.max_retries}")
                from agents.developer import DeveloperAgent
                dev = DeveloperAgent(state, board, logger)
                dev.run()
                state.test_runs.clear()
                state.last_edit_time = _now()
                # Re-run verifier and reviewer after fix
                continue

            # All done -> human approval
            if not self._open_review_issues():
                state.status = RunStatus.AWAITING_HUMAN
                print(f"\n✅ All checks passed. Requesting human approval...")
                self._request_human_approval()
                break

        if state.status not in (RunStatus.DONE, RunStatus.ESCALATED, RunStatus.STOPPED):
            if self._step_count >= self._max_global_steps:
                self._escalate(f"Reached max global steps ({self._max_global_steps})")

        logger.log("orchestrator", "RUN_END",
                   output_summary=f"status={state.status}, steps={self._step_count}")

    def _request_human_approval(self) -> None:
        """Show diff + report, ask for approve/reject."""
        from tools.git_tools import git_diff as compute_diff

        diff = compute_diff(self.state.repo_path, self.state.workspace_path)

        print("\n" + "="*60)
        print("FINAL DIFF:")
        print("="*60)
        print(diff[:3000] if diff else "(no changes)")
        print("="*60)

        # Show criteria summary
        print("\n📊 Criteria Summary:")
        for c in self.state.criteria:
            icon = "✅" if c.status == "met" else "❌" if c.status == "failed" else "⏳"
            print(f"  {icon} {c.id}: {c.text}")

        # Show review issues
        if self.state.review_issues:
            print("\n🔍 Review Issues:")
            for issue in self.state.review_issues:
                icon = "🔴" if issue.status == "open" else "✅"
                print(f"  {icon} [{issue.severity}] {issue.file}:{issue.line} - {issue.text}")

        # Generate report
        self._generate_report()

        # Ask for approval
        print("\n" + "="*60)
        try:
            answer = input("Approve changes? [y/N]: ").strip().lower()
        except EOFError:
            answer = "n"

        if answer in ("y", "yes"):
            self._apply_changes()
            self.state.status = RunStatus.DONE
            print("✅ Changes applied to the original repo.")
        else:
            self.state.status = RunStatus.STOPPED
            print("❌ Changes rejected. Original repo unchanged.")

        self.logger.log(
            "orchestrator",
            "HUMAN_DECISION",
            output_summary=f"approved={answer in ('y', 'yes')}",
        )

    def _apply_changes(self) -> None:
        """Copy changed files from workspace to original repo."""
        ws = Path(self.workspace_path)
        orig = Path(self.state.repo_path)
        for src in ws.rglob("*"):
            if src.is_file():
                rel = src.relative_to(ws)
                dest = orig / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dest))
        self.logger.log("orchestrator", "CHANGES_APPLIED",
                        output_summary=f"from {self.workspace_path} to {self.state.repo_path}")

    def _generate_report(self) -> None:
        """Write runs/<run_id>_report.md."""
        from pathlib import Path as P
        runs_dir = P(__file__).parent.parent / "runs"
        runs_dir.mkdir(exist_ok=True)
        report_path = runs_dir / f"{self.run_id}_report.md"

        reduced = any(
            tr.exit_code == 127 for tr in self.state.test_runs
        )

        lines = [
            f"# DevPilot Report: {self.run_id}\n",
            f"**Request:** {self.state.request}\n",
            f"**Status:** {self.state.status}\n",
            f"**Retries used:** {self.state.retries}/{self.state.max_retries}\n",
            "\n## Changed Files\n",
        ]

        # List files that differ
        from tools.git_tools import git_diff
        diff = git_diff(self.state.repo_path, self.state.workspace_path)
        if diff:
            for line in diff.splitlines():
                if line.startswith("diff --git"):
                    lines.append(f"- {line.replace('diff --git ', '')}")
        else:
            lines.append("- (no changes)")

        lines.append("\n## VERIFIED\n")
        for c in self.state.criteria:
            if c.status == "met":
                lines.append(f"- ✅ **{c.id}**: {c.text}")
                if c.evidence:
                    lines.append(f"  - Evidence: {c.evidence}")

        lines.append("\n## NOT VERIFIED\n")
        for c in self.state.criteria:
            if c.status != "met":
                lines.append(f"- ❌ **{c.id}**: {c.text} [{c.status}]")
                if c.evidence:
                    lines.append(f"  - Evidence: {c.evidence}")

        lines.append("\n## Open Issues\n")
        open_issues = [i for i in self.state.review_issues if i.status == "open"]
        if open_issues:
            for issue in open_issues:
                lines.append(f"- [{issue.severity}] {issue.file}:{issue.line} - {issue.text}")
        else:
            lines.append("- None")

        lines.append("\n## Test Runs\n")
        for tr in self.state.test_runs:
            lines.append(f"- `{tr.command}` → exit {tr.exit_code}")

        if reduced:
            lines.append(
                "\n> ⚠️  **Reduced coverage**: Test runner was unavailable. "
                "Fallback checks were used. Full test coverage not guaranteed.\n"
            )

        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n📄 Report saved to: {report_path}")
        self.logger.log("orchestrator", "REPORT_GENERATED",
                        output_summary=str(report_path))
