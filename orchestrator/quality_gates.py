"""Quality gate framework for pre-validation enforcement.

Quality gates run against a task's report before validation passes.
Each gate has a policy of "fail" (blocks validation) or "warn" (advisory only).
Gates are configured in the policy triggers under "quality_gates".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GateResult:
    gate: str
    passed: bool
    policy: str  # "fail" or "warn"
    message: str


@dataclass
class QualityGateOutcome:
    all_passed: bool
    results: List[GateResult] = field(default_factory=list)
    blocking: List[GateResult] = field(default_factory=list)
    warnings: List[GateResult] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        for r in self.blocking:
            parts.append(f"BLOCKED[{r.gate}]: {r.message}")
        for r in self.warnings:
            parts.append(f"WARN[{r.gate}]: {r.message}")
        return "; ".join(parts) if parts else "all gates passed"


# ---------------------------------------------------------------------------
# Built-in gate implementations
# ---------------------------------------------------------------------------

def _gate_test_completeness(
    report: Dict[str, Any],
    task: Dict[str, Any],
    config: Dict[str, Any],
) -> GateResult:
    """Ensures tests actually ran (passed > 0), not just 0 failures."""
    policy = str(config.get("policy", "fail"))
    min_passed = int(config.get("min_passed", 1))
    summary = report.get("test_summary") or {}
    passed_count = int(summary.get("passed", 0))
    has_command = bool(str(summary.get("command", "")).strip())

    if not has_command:
        return GateResult(
            gate="test_completeness",
            passed=False,
            policy=policy,
            message="No test command recorded in report",
        )
    if passed_count < min_passed:
        return GateResult(
            gate="test_completeness",
            passed=False,
            policy=policy,
            message=f"Only {passed_count} tests passed (minimum: {min_passed})",
        )
    return GateResult(gate="test_completeness", passed=True, policy=policy, message="ok")


def _gate_arch_check(
    report: Dict[str, Any],
    task: Dict[str, Any],
    config: Dict[str, Any],
) -> GateResult:
    """Checks artifacts for forbidden architectural patterns."""
    policy = str(config.get("policy", "warn"))
    forbidden = config.get("forbidden_patterns", [])
    if not isinstance(forbidden, list):
        forbidden = []

    artifacts = report.get("artifacts") or []
    if not isinstance(artifacts, list):
        artifacts = []
    notes = str(report.get("notes", ""))

    violations: List[str] = []
    searchable = " ".join(str(a) for a in artifacts) + " " + notes
    for pattern in forbidden:
        if str(pattern).lower() in searchable.lower():
            violations.append(str(pattern))

    if violations:
        return GateResult(
            gate="arch_check",
            passed=False,
            policy=policy,
            message=f"Forbidden patterns found: {', '.join(violations)}",
        )
    return GateResult(gate="arch_check", passed=True, policy=policy, message="ok")


def _gate_anti_pattern(
    report: Dict[str, Any],
    task: Dict[str, Any],
    config: Dict[str, Any],
) -> GateResult:
    """Detects common report anti-patterns that indicate low-quality submissions."""
    policy = str(config.get("policy", "fail"))
    issues: List[str] = []

    commit_sha = str(report.get("commit_sha", "")).strip()
    if commit_sha in ("", "none", "n/a", "placeholder", "unknown"):
        issues.append("placeholder or empty commit_sha")

    summary = report.get("test_summary") or {}
    command = str(summary.get("command", "")).strip()
    if command in ("", "none", "n/a", "echo ok", "true"):
        issues.append(f"suspicious test command: '{command}'")

    notes = str(report.get("notes", "")).strip()
    if len(notes) > 0 and len(notes) < 5:
        issues.append("report notes too short to be meaningful")

    status = str(report.get("status", "")).strip().lower()
    failed = int(summary.get("failed", 0))
    if status == "done" and failed > 0:
        issues.append(f"status=done but {failed} tests failed")

    if issues:
        return GateResult(
            gate="anti_pattern",
            passed=False,
            policy=policy,
            message=f"Anti-patterns detected: {'; '.join(issues)}",
        )
    return GateResult(gate="anti_pattern", passed=True, policy=policy, message="ok")


# ---------------------------------------------------------------------------
# Gate registry and runner
# ---------------------------------------------------------------------------

GATE_REGISTRY = {
    "test_completeness": _gate_test_completeness,
    "arch_check": _gate_arch_check,
    "anti_pattern": _gate_anti_pattern,
}


def run_quality_gates(
    report: Dict[str, Any],
    task: Dict[str, Any],
    gates_config: Dict[str, Any],
) -> QualityGateOutcome:
    """Run all configured quality gates against a report.

    Args:
        report: The submitted report dict.
        task: The task dict being validated.
        gates_config: The "quality_gates" section from policy triggers.
            Expected shape: {"enabled": true, "gates": {"gate_name": {"policy": "fail"|"warn", ...}}}

    Returns:
        QualityGateOutcome with aggregated results.
    """
    if not isinstance(gates_config, dict):
        return QualityGateOutcome(all_passed=True)

    if not gates_config.get("enabled", False):
        return QualityGateOutcome(all_passed=True)

    gates = gates_config.get("gates", {})
    if not isinstance(gates, dict):
        return QualityGateOutcome(all_passed=True)

    results: List[GateResult] = []
    blocking: List[GateResult] = []
    warnings: List[GateResult] = []

    for gate_name, gate_cfg in gates.items():
        if not isinstance(gate_cfg, dict):
            continue
        gate_fn = GATE_REGISTRY.get(gate_name)
        if gate_fn is None:
            continue
        result = gate_fn(report=report, task=task, config=gate_cfg)
        results.append(result)
        if not result.passed:
            if result.policy == "fail":
                blocking.append(result)
            else:
                warnings.append(result)

    return QualityGateOutcome(
        all_passed=len(blocking) == 0,
        results=results,
        blocking=blocking,
        warnings=warnings,
    )
