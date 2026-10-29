"""JSONL run logger for DevPilot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


RUNS_DIR = Path(__file__).parent.parent / "runs"


def _now() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


class RunLogger:
    """Appends one JSON line per event to runs/<run_id>.jsonl."""

    def __init__(self, run_id: str):
        """Open (or create) the log file for run_id."""
        RUNS_DIR.mkdir(exist_ok=True)
        self.path = RUNS_DIR / f"{run_id}.jsonl"
        self.run_id = run_id

    def log(
        self,
        agent: str,
        event_type: str,
        tool: str = "",
        input_summary: str = "",
        output_summary: str = "",
        extra: dict | None = None,
    ) -> None:
        """Append one event line to the log."""
        record: dict = {
            "time": _now(),
            "agent": agent,
            "event_type": event_type,
            "tool": tool,
            "input": input_summary,
            "output_summary": output_summary,
        }
        if extra:
            record.update(extra)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    def read_all(self) -> list[dict]:
        """Return all log records as a list of dicts."""
        if not self.path.exists():
            return []
        records = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
