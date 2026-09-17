"""Native-render budget ledger (Phase 2 design decision, pinned down here).

Design decision (see docs/plan/ERRATA_AND_REVISIONS.md item 4b): the pack
mentions compute budgets for native calls but had no accounting mechanism.
The resolution is a small persistent JSON sidecar file, one per dataset,
tracking cumulative counters across resumable collection sessions:

  {
    "version": "dexfrag-budget-v1",
    "renders_attempted": <int>,
    "renders_valid": <int>,
    "elapsed_seconds": <float>,
    "dataset_bytes": <int>,
    "sessions": <int>
  }

A ``Budget`` is loaded from (and persisted back to) this sidecar file next to
the dataset, so a collector can be interrupted (Ctrl+C, crash, machine
restart) and resumed without ever exceeding a caller-specified cap on
attempted renders, wall-clock time, or dataset disk size. Caps are optional;
omitting one means "no limit on that dimension." The ledger is authoritative
for *this dataset file*, not global -- multiple datasets each get their own
ledger.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

BUDGET_VERSION = "dexfrag-budget-v1"


class BudgetExceeded(RuntimeError):
    """Raised when a caller-specified cap would be exceeded by the next unit of work."""


@dataclass
class BudgetCaps:
    max_renders_attempted: int | None = None
    max_elapsed_seconds: float | None = None
    max_dataset_bytes: int | None = None


@dataclass
class Budget:
    """Cumulative ledger for one dataset file, persisted as JSON alongside it."""

    ledger_path: Path
    renders_attempted: int = 0
    renders_valid: int = 0
    elapsed_seconds: float = 0.0
    dataset_bytes: int = 0
    sessions: int = 0
    _session_start: float = 0.0

    @classmethod
    def load(cls, dataset_path: Path | str) -> "Budget":
        dataset_path = Path(dataset_path)
        ledger_path = cls._ledger_path_for(dataset_path)
        if ledger_path.exists():
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
            budget = cls(
                ledger_path=ledger_path,
                renders_attempted=payload.get("renders_attempted", 0),
                renders_valid=payload.get("renders_valid", 0),
                elapsed_seconds=payload.get("elapsed_seconds", 0.0),
                dataset_bytes=payload.get("dataset_bytes", 0),
                sessions=payload.get("sessions", 0),
            )
        else:
            budget = cls(ledger_path=ledger_path)
        budget.sessions += 1
        budget._session_start = time.monotonic()
        return budget

    @staticmethod
    def _ledger_path_for(dataset_path: Path) -> Path:
        return dataset_path.with_suffix(dataset_path.suffix + ".budget.json")

    def save(self) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": BUDGET_VERSION,
            "renders_attempted": self.renders_attempted,
            "renders_valid": self.renders_valid,
            "elapsed_seconds": self.elapsed_seconds,
            "dataset_bytes": self.dataset_bytes,
            "sessions": self.sessions,
        }
        self.ledger_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _current_elapsed_seconds(self) -> float:
        return self.elapsed_seconds + (time.monotonic() - self._session_start)

    def check_can_attempt_one_more(self, caps: BudgetCaps) -> None:
        """Raise BudgetExceeded if attempting one more render would violate a cap.

        Checked *before* each render so a caller never overshoots a hard cap,
        even by one unit -- important for the bounded 64-observation smoke
        test and any operator-configured bounded profile.
        """
        if caps.max_renders_attempted is not None and self.renders_attempted >= caps.max_renders_attempted:
            raise BudgetExceeded(
                f"renders_attempted cap reached ({self.renders_attempted}/{caps.max_renders_attempted})."
            )
        if caps.max_elapsed_seconds is not None and self._current_elapsed_seconds() >= caps.max_elapsed_seconds:
            raise BudgetExceeded(
                f"elapsed_seconds cap reached ({self._current_elapsed_seconds():.1f}/{caps.max_elapsed_seconds}s)."
            )
        if caps.max_dataset_bytes is not None and self.dataset_bytes >= caps.max_dataset_bytes:
            raise BudgetExceeded(
                f"dataset_bytes cap reached ({self.dataset_bytes}/{caps.max_dataset_bytes})."
            )

    def record_attempt(self, *, valid: bool) -> None:
        self.renders_attempted += 1
        if valid:
            self.renders_valid += 1
        self.elapsed_seconds = self._current_elapsed_seconds()
        self._session_start = time.monotonic()

    def refresh_dataset_bytes(self, dataset_path: Path | str) -> None:
        dataset_path = Path(dataset_path)
        self.dataset_bytes = dataset_path.stat().st_size if dataset_path.exists() else 0

    def to_dict(self) -> dict:
        return {
            "version": BUDGET_VERSION,
            "renders_attempted": self.renders_attempted,
            "renders_valid": self.renders_valid,
            "elapsed_seconds": self.elapsed_seconds,
            "dataset_bytes": self.dataset_bytes,
            "sessions": self.sessions,
        }
