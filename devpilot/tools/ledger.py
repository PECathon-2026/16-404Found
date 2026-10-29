"""Evidence ledger implementation writing raw logs and maintaining verifiable evidence.

Implements `ports.EvidenceLedger` storing outputs in `runs/<mission_id>/evidence/E-XXXX.log`
with cryptographic SHA256 digests and sequential IDs numbered per mission.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from devpilot.core.models import Evidence


class FileEvidenceLedger:
    """Thread/async-safe file-backed evidence ledger."""

    def __init__(self, root_dir: Path | str = "runs", mission_id: str | None = None) -> None:
        self.root_dir = Path(root_dir)
        self.mission_id = mission_id
        self._lock = asyncio.Lock()
        self._counter: int = 0
        self._records: dict[str, Evidence] = {}

    def _evidence_dir(self) -> Path:
        if self.root_dir.name == "evidence":
            p = self.root_dir
        elif self.mission_id:
            p = self.root_dir / self.mission_id / "evidence"
        else:
            p = self.root_dir / "evidence"
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def record(self, ev: Evidence, raw_output: str) -> Evidence:
        """Assign sequential id per mission, persist raw log, calculate sha256, and store record."""
        async with self._lock:
            self._counter += 1
            evidence_id = f"E-{self._counter:04d}"
            ev_dir = self._evidence_dir()
            log_file = ev_dir / f"{evidence_id}.log"

            # Compute sha256 of raw output bytes
            raw_bytes = raw_output.encode("utf-8")
            digest = hashlib.sha256(raw_bytes).hexdigest()

            # Write raw log asynchronously via threadpool
            await asyncio.to_thread(log_file.write_bytes, raw_bytes)

            updated = ev.model_copy(
                update={
                    "id": evidence_id,
                    "sha256": digest,
                    "log_path": log_file.as_posix(),
                }
            )
            self._records[evidence_id] = updated
            return updated

    def get(self, evidence_id: str) -> Evidence:
        """Retrieve recorded evidence by ID or raise KeyError."""
        if evidence_id not in self._records:
            raise KeyError(f"Evidence record {evidence_id!r} not found in ledger")
        return self._records[evidence_id]

    def exists(self, evidence_id: str) -> bool:
        """Check whether an evidence ID has been recorded."""
        return evidence_id in self._records
