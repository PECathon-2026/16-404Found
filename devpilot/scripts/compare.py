"""Compare single-agent baseline vs DevPilot multi-agent system."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()


SCENARIOS = [
    {
        "name": "mini_shop_coupon",
        "repo": "demo_repos/mini_shop",
        "request": "Add coupon support. SAVE10 gives 10% off. Apply via cart.total_with_coupon('SAVE10').",
    },
    {
        "name": "bugfix",
        "repo": "demo_repos/bugfix_repo",
        "request": "Fix the off-by-one bug in get_top_n so it returns exactly n items.",
    },
    {
        "name": "security",
        "repo": "demo_repos/security_repo",
        "request": "Fix SQL injection vulnerabilities and remove the hardcoded password.",
    },
]


def run_baseline_scenario(scenario: dict, root: Path) -> dict:
    """Run single-agent baseline on a scenario."""
    from baseline.single_agent import run_single_agent
    import unittest.mock as mock

    repo = root / scenario["repo"]
    start = time.time()
    try:
        with mock.patch("builtins.input", return_value="n"):
            result = run_single_agent(str(repo), scenario["request"])
        elapsed = time.time() - start
        return {
            "name": scenario["name"],
            "agent": "baseline",
            "success": result["success"],
            "steps": result["steps"],
            "bugs_caught": result["bugs_caught"],
            "secrets_caught": result["secrets_caught"],
            "safety_blocks": 0,
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as exc:
        return {
            "name": scenario["name"],
            "agent": "baseline",
            "error": str(exc)[:100],
            "success": False,
            "elapsed_s": round(time.time() - start, 1),
        }


def run_devpilot_scenario(scenario: dict, root: Path) -> dict:
    """Run DevPilot multi-agent on a scenario."""
    from core.orchestrator import Orchestrator
    import unittest.mock as mock

    repo = root / scenario["repo"]
    start = time.time()
    try:
        orchestrator = Orchestrator(repo_path=repo, request=scenario["request"])
        with mock.patch("builtins.input", return_value="n"):
            orchestrator.run()
        elapsed = time.time() - start

        state = orchestrator.state
        log_records = orchestrator.logger.read_all()
        safety_blocks = sum(1 for r in log_records if r.get("event_type") == "BLOCKED")
        secrets = sum(
            1 for i in state.review_issues
            if "key" in i.text.lower() or "secret" in i.text.lower() or "password" in i.text.lower()
        )
        # Count bugs caught = criteria that were met after fixing
        bugs = sum(1 for c in state.criteria if c.status == "met")

        return {
            "name": scenario["name"],
            "agent": "devpilot",
            "success": state.status in ("done", "awaiting_human"),
            "retries": state.retries,
            "bugs_caught": bugs,
            "secrets_caught": secrets,
            "safety_blocks": safety_blocks,
            "elapsed_s": round(elapsed, 1),
        }
    except Exception as exc:
        return {
            "name": scenario["name"],
            "agent": "devpilot",
            "error": str(exc)[:100],
            "success": False,
            "elapsed_s": round(time.time() - start, 1),
        }


def main():
    """Run comparison and print table."""
    root = Path(__file__).parent.parent
    rows = []

    for scenario in SCENARIOS:
        print(f"\nRunning scenario: {scenario['name']}")
        print("  [Baseline]...")
        baseline = run_baseline_scenario(scenario, root)
        rows.append(baseline)
        print(f"  [DevPilot]...")
        devpilot = run_devpilot_scenario(scenario, root)
        rows.append(devpilot)

    print("\n" + "="*90)
    print("COMPARISON TABLE: Single-Agent Baseline vs DevPilot")
    print("="*90)
    print(f"{'Scenario':<22} {'Agent':<12} {'Success':<9} {'Retries':<9} {'Bugs':<7} {'Secrets':<9} {'Blocks':<8} {'Time(s)'}")
    print("-"*90)
    for r in rows:
        print(
            f"{r['name']:<22} "
            f"{r['agent']:<12} "
            f"{'✅' if r.get('success') else '❌':<9} "
            f"{r.get('retries', r.get('steps', '-')):<9} "
            f"{r.get('bugs_caught', 0):<7} "
            f"{r.get('secrets_caught', 0):<9} "
            f"{r.get('safety_blocks', 0):<8} "
            f"{r.get('elapsed_s', '?')}"
        )
    print("="*90)

    # Save
    out_path = root / "runs" / "comparison_results.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
