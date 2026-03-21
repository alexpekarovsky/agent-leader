"""Iterative self-review loop scaffold.

Provides a configurable multi-round self-review mechanism that workers
execute *before* submitting their report to the manager.  Each round
produces a structured critique; the loop exits early when the worker
signals readiness or the maximum number of rounds is reached.

Policy configuration (in triggers.self_review):
    enabled          – bool, default False
    max_rounds       – int, max critique rounds (default 2)
    min_rounds       – int, minimum rounds before early-exit (default 1)

Integration point:
    Worker flow:  [implementation] → [tests] → [self-review loop] → [submit report]
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelfReviewConfig:
    """Policy-driven configuration for the self-review loop."""

    enabled: bool = False
    max_rounds: int = 2
    min_rounds: int = 1

    @staticmethod
    def from_policy(triggers: Dict[str, Any]) -> "SelfReviewConfig":
        """Build config from the ``triggers`` section of a policy dict."""
        raw = triggers.get("self_review", {})
        if not isinstance(raw, dict):
            return SelfReviewConfig()
        return SelfReviewConfig(
            enabled=bool(raw.get("enabled", False)),
            max_rounds=max(1, int(raw.get("max_rounds", 2))),
            min_rounds=max(1, int(raw.get("min_rounds", 1))),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_rounds": self.max_rounds,
            "min_rounds": self.min_rounds,
        }


# ---------------------------------------------------------------------------
# Round tracking
# ---------------------------------------------------------------------------

@dataclass
class SelfReviewRound:
    """Outcome of a single self-review round."""

    round_number: int
    verdict: str  # "needs_revision" | "ready"
    findings: List[str] = field(default_factory=list)
    revised_files: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.verdict not in ("needs_revision", "ready"):
            raise ValueError(
                f"Invalid verdict '{self.verdict}'; must be 'needs_revision' or 'ready'"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_number": self.round_number,
            "verdict": self.verdict,
            "findings": list(self.findings),
            "revised_files": list(self.revised_files),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Loop outcome
# ---------------------------------------------------------------------------

@dataclass
class SelfReviewOutcome:
    """Aggregate result of the entire self-review loop."""

    config: SelfReviewConfig
    rounds: List[SelfReviewRound] = field(default_factory=list)
    status: str = "pending"  # "pending" | "passed" | "max_rounds_reached"

    @property
    def total_rounds(self) -> int:
        return len(self.rounds)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    @property
    def current_round(self) -> int:
        """Next round number (1-indexed)."""
        return len(self.rounds) + 1

    def summary(self) -> str:
        if self.status == "passed":
            return f"self-review passed after {self.total_rounds} round(s)"
        if self.status == "max_rounds_reached":
            return f"self-review exhausted {self.config.max_rounds} round(s)"
        return f"self-review pending (round {self.current_round}/{self.config.max_rounds})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "rounds": [r.to_dict() for r in self.rounds],
            "status": self.status,
            "total_rounds": self.total_rounds,
            "summary": self.summary(),
        }


# ---------------------------------------------------------------------------
# Loop controller
# ---------------------------------------------------------------------------

class SelfReviewLoop:
    """Controls the iterative self-review lifecycle for a single task.

    Usage::

        loop = SelfReviewLoop(config)
        while not loop.is_complete():
            # worker performs critique …
            loop.record_round(verdict="needs_revision", findings=["issue X"])
            # worker revises …
        # or:
        loop.record_round(verdict="ready")
        outcome = loop.outcome()
    """

    def __init__(self, config: SelfReviewConfig) -> None:
        self._outcome = SelfReviewOutcome(config=config)

    # -- state queries -------------------------------------------------------

    def is_complete(self) -> bool:
        return self._outcome.status in ("passed", "max_rounds_reached")

    def can_exit_early(self) -> bool:
        """True when minimum rounds have been completed."""
        return self._outcome.total_rounds >= self._outcome.config.min_rounds

    def rounds_remaining(self) -> int:
        return max(0, self._outcome.config.max_rounds - self._outcome.total_rounds)

    # -- mutations -----------------------------------------------------------

    def record_round(
        self,
        verdict: str,
        findings: Optional[List[str]] = None,
        revised_files: Optional[List[str]] = None,
    ) -> SelfReviewRound:
        """Record the outcome of the current review round.

        Raises ``RuntimeError`` if the loop is already complete.
        """
        if self.is_complete():
            raise RuntimeError(
                f"Self-review loop already complete (status={self._outcome.status})"
            )

        rnd = SelfReviewRound(
            round_number=self._outcome.current_round,
            verdict=verdict,
            findings=findings or [],
            revised_files=revised_files or [],
        )
        self._outcome.rounds.append(rnd)

        # Transition logic
        if verdict == "ready" and self.can_exit_early():
            self._outcome.status = "passed"
        elif verdict == "ready" and not self.can_exit_early():
            # Still need more rounds even if worker says ready
            pass
        elif self._outcome.total_rounds >= self._outcome.config.max_rounds:
            self._outcome.status = "max_rounds_reached"

        return rnd

    # -- output --------------------------------------------------------------

    def outcome(self) -> SelfReviewOutcome:
        return self._outcome


# ---------------------------------------------------------------------------
# Convenience: build loop from policy triggers
# ---------------------------------------------------------------------------

def create_self_review_loop(triggers: Dict[str, Any]) -> Optional[SelfReviewLoop]:
    """Create a self-review loop from policy triggers.

    Returns ``None`` if self-review is disabled in the policy.
    """
    config = SelfReviewConfig.from_policy(triggers)
    if not config.enabled:
        return None
    return SelfReviewLoop(config)
