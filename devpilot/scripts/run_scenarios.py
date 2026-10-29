"""Run all DevPilot scenarios and produce a results table."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add devpilot root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


SCENARIOS = [
    {
        "name": "mini_shop_coupon",
        "repo": "demo_repos/mini_shop",
        "request": "Add coupon support. SAVE10 gives 10% off. Apply via cart.total_with_coupon('SAVE10').",
        "simulate_missing": None,
        "expected": "awaiting_human",
    },
    {
        "name": "ambiguous_request",
        "repo": "demo_repos/mini_shop",
        "request": "add a discount",
        "simulate_missing": None,
        "expected": "stopped",  # Should trigger CLARIFY
    },
    {
        "name": "bugfix",
        "repo": "demo_repos/bugfix_repo",
        "request": "Fix the off-by-one bug in get_top_n so it returns exactly n items.",
        "simulate_missing": None,
        "expected": "awaiting_human",
    },
    {
        "name": "failing_test",
        "repo": "demo_repos/failing_test_repo",
        "request": "Fix the failing test: add a 'say_hello' alias or rename 'greet' to 'say_hello' in greeter.py.",
        "simulate_missing": None,
        "expected": "awaiting_human",
    },
    {
        "name": "security",
        "repo": "demo_repos/security_repo",
        "request": "Fix the SQL injection vulnerabilities in db.py using parameterized queries and remove the hardcoded password.",
        "simulate_missing": None,
        "expected": "awaiting_human",
    },
    {
        "name": "stuck",
        "repo": "demo_repos/stuck_repo",
        "request": "Make compute_answer() return exactly 42.",
        "simulate_missing": None,
        "expected": "escalated",
    },
    {
        "name": "notools",
        "repo": "demo_repos/notools_repo",
        "request": "Add a modulo function to math_ops.py: modulo(a, b) returns a % b, raises ValueError if b == 0.",
        "simulate_missing": "pytest",
        "expected": "awaiting_human",  # With reduced coverage note
    },
    {
        "name": "revision",
        "repo": "demo_repos/revision_repo",
        "request": "Change the tax rate in apply_tax from 10% to 15%.",
        "simulate_missing": None,
        "expected": "awaiting_human",
    },
]


def run_scenario(scenario: dict, devpilot_root: Path) -> dict:
    """Run one scenario and return results."""
    from core.orchestrator import Orchestrator
    from core.board import MessageBoard
    from core.logger import RunLogger

    repo_path = devpilot_root / scenario["repo"]
    print(f"\n{'='*60}")
    print(f"Scenario: {scenario['name']}")
    print(f"Repo: {repo_path}")
    print(f"Request: {scenario['request'][:80]}")
    print("="*60)

    start_time = time.time()

    try:
        orchestrator = Orchestrator(
            repo_path=repo_path,
            request=scenario["request"],
            simulate_missing=scenario.get("simulate_missing"),
        )

        # Run non-interactively (auto-reject approval for scenarios)
        import unittest.mock as mock

        with mock.patch("builtins.input", return_value="n"):
            orchestrator.run()

        elapsed = time.time() - start_time
        state = orchestrator.state
        log_records = orchestrator.logger.read_all()

        # Determine outcomes
        has_clarify = orchestrator.board.has_type("CLARIFY")
        has_escalate = orchestrator.board.has_type("ESCALATE")
        has_plan_revised = orchestrator.board.has_type("PLAN_REVISED")
        has_plan_gap = any(r.get("event_type") == "PLAN_GAP" for r in log_records)
        has_blocked = any(r.get("event_type") == "BLOCKED" for r in log_records)
        has_tool_unavailable = orchestrator.board.has_type("TOOL_UNAVAILABLE")
        has_reduced_coverage = any(
            tr.exit_code == 127 for tr in state.test_runs
        )
        review_issues = len(state.review_issues)
        retries = state.retries

        result = {
            "scenario": scenario["name"],
            "status": str(state.status),
            "expected": scenario["expected"],
            "passed": str(state.status) == scenario["expected"],
            "elapsed_s": round(elapsed, 1),
            "retries": retries,
            "has_clarify": has_clarify,
            "has_escalate": has_escalate,
            "has_plan_revised": has_plan_revised,
            "has_plan_gap": has_plan_gap,
            "has_blocked_command": has_blocked,
            "has_tool_unavailable": has_tool_unavailable,
            "reduced_coverage": has_reduced_coverage,
            "review_issues": review_issues,
            "run_id": state.run_id,
            "log_path": str(orchestrator.logger.path),
        }

    except Exception as exc:
        elapsed = time.time() - start_time
        result = {
            "scenario": scenario["name"],
            "status": "error",
            "expected": scenario["expected"],
            "passed": False,
            "elapsed_s": round(elapsed, 1),
            "error": str(exc)[:200],
        }
        print(f"ERROR in scenario {scenario['name']}: {exc}")
        import traceback
        traceback.print_exc()

    return result


def print_results_table(results: list[dict]) -> None:
    """Print a formatted results table."""
    print("\n" + "="*100)
    print("SCENARIO RESULTS TABLE")
    print("="*100)
    print(f"{'Scenario':<25} {'Status':<18} {'Expected':<18} {'Pass':<6} {'Retries':<8} {'Clarify':<8} {'Escalate':<9} {'Revised':<8} {'Blocked':<8} {'NoTool':<7} {'Issues'}")
    print("-"*100)
    for r in results:
        icon = "✅" if r.get("passed") else "❌"
        print(
            f"{r['scenario']:<25} "
            f"{r.get('status','?'):<18} "
            f"{r.get('expected','?'):<18} "
            f"{icon:<6} "
            f"{r.get('retries', '-'):<8} "
            f"{'Y' if r.get('has_clarify') else 'N':<8} "
            f"{'Y' if r.get('has_escalate') else 'N':<9} "
            f"{'Y' if r.get('has_plan_revised') else 'N':<8} "
            f"{'Y' if r.get('has_blocked_command') else 'N':<8} "
            f"{'Y' if r.get('has_tool_unavailable') else 'N':<7} "
            f"{r.get('review_issues', 0)}"
        )
    print("="*100)

    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n{passed}/{len(results)} scenarios passed expected outcomes.\n")


def main():
    """Run all scenarios."""
    devpilot_root = Path(__file__).parent.parent
    all_results = []

    for scenario in SCENARIOS:
        result = run_scenario(scenario, devpilot_root)
        all_results.append(result)

        # Save intermediate results
        results_path = devpilot_root / "runs" / "scenario_results.json"
        results_path.parent.mkdir(exist_ok=True)
        results_path.write_text(json.dumps(all_results, indent=2))

    print_results_table(all_results)

    # Save final results
    results_path = devpilot_root / "runs" / "scenario_results.json"
    results_path.write_text(json.dumps(all_results, indent=2))
    print(f"Results saved to: {results_path}")


if __name__ == "__main__":
    main()
