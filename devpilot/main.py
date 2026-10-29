"""DevPilot entry point - multi-agent AI system for code changes."""

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def main():
    """Parse CLI args and run the DevPilot orchestrator."""
    parser = argparse.ArgumentParser(
        description="DevPilot: Multi-agent AI code change system"
    )
    parser.add_argument("--repo", required=True, help="Path to target repo")
    parser.add_argument("--request", required=True, help="Plain-English change request")
    parser.add_argument(
        "--simulate-missing",
        default=None,
        help="Simulate a missing tool (e.g. pytest)",
    )
    args = parser.parse_args()

    repo_path = Path(args.repo).resolve()
    if not repo_path.exists():
        print(f"Error: repo path {repo_path} does not exist", file=sys.stderr)
        sys.exit(1)

    from core.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        repo_path=repo_path,
        request=args.request,
        simulate_missing=args.simulate_missing,
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
