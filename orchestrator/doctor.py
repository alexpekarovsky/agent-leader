from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _hint_for_binding_warning(warning: str) -> Optional[str]:
    if warning.startswith("startup_cwd_root_mismatch"):
        return "Restart MCP from the project root or set ORCHESTRATOR_ROOT/ORCHESTRATOR_EXPECTED_ROOT explicitly."
    if warning == "shared_install_without_orchestrator_root_env":
        return "Set ORCHESTRATOR_ROOT in MCP server env to prevent shared-install cross-project binding leaks."
    if warning == "shared_install_without_expected_root_env":
        return "Set ORCHESTRATOR_EXPECTED_ROOT and keep it equal to ORCHESTRATOR_ROOT."
    return None


def _hint_for_identity_reason(reason: str) -> Optional[str]:
    if reason.startswith("missing_identity_fields"):
        return "Reconnect via orchestrator_connect_to_leader with full identity metadata."
    if reason == "project_mismatch":
        return "Agent project_root/cwd does not match this project; correct context and reconnect."
    if reason == "no_recent_heartbeat":
        return "Agent heartbeat is stale; send orchestrator_heartbeat or reconnect to leader."
    if reason == "not_registered":
        return "Register the agent first (orchestrator_register_agent), then reconnect to leader."
    return None


def build_doctor_payload(
    *,
    root_dir: Path,
    policy_path: Path,
    policy_name: str,
    policy_loaded: bool,
    binding_error: Optional[str],
    server_binding: Dict[str, Any],
    runtime_source_consistency: Dict[str, Any],
    manager: Optional[str],
    roles: Dict[str, Any],
    agents: List[Dict[str, Any]],
    discovered: Dict[str, Any],
    orch_available: bool,
) -> Dict[str, Any]:
    root_exists = root_dir.exists()
    policy_exists = policy_path.exists()
    binding_ok = bool(server_binding.get("ok", False))
    source_ok = bool(runtime_source_consistency.get("ok", False))

    active_agents = [a for a in agents if a.get("status") == "active"]
    offline_agents = [a for a in agents if a.get("status") != "active"]
    verified_active = [
        a for a in active_agents if bool(a.get("verified")) and bool(a.get("same_project"))
    ]
    auth_failures = [
        {
            "agent": a.get("agent"),
            "reason": a.get("reason"),
            "status": a.get("status"),
            "same_project": bool(a.get("same_project")),
            "verified": bool(a.get("verified")),
        }
        for a in agents
        if not (bool(a.get("verified")) and bool(a.get("same_project")))
    ]

    auth_ok = len(auth_failures) == 0 and (len(agents) == 0 or len(verified_active) > 0)
    connectivity_ok = len(active_agents) > 0 if agents else True
    root_ok = root_exists and binding_ok and not bool(binding_error)
    policy_ok = policy_exists and policy_loaded

    checks = {
        "root": {
            "ok": root_ok,
            "root_dir": str(root_dir),
            "root_exists": root_exists,
            "binding_error": binding_error,
            "server_binding": server_binding,
        },
        "policy": {
            "ok": policy_ok,
            "policy_name": policy_name,
            "policy_path": str(policy_path),
            "policy_exists": policy_exists,
            "policy_loaded": policy_loaded,
        },
        "auth": {
            "ok": auth_ok,
            "registered_agents": len(agents),
            "verified_active_agents": len(verified_active),
            "verification_failures": auth_failures,
        },
        "connectivity": {
            "ok": connectivity_ok,
            "active_agents": len(active_agents),
            "offline_agents": len(offline_agents),
            "registered_count": int(discovered.get("registered_count", len(agents))),
            "inferred_only_count": int(discovered.get("inferred_only_count", 0)),
        },
        "source_consistency": {
            "ok": source_ok,
            **runtime_source_consistency,
        },
    }

    hints: List[str] = []
    if binding_error:
        hints.append(
            "Binding is degraded. Validate ORCHESTRATOR_ROOT, ORCHESTRATOR_EXPECTED_ROOT, and ORCHESTRATOR_POLICY."
        )
    if not root_exists:
        hints.append("Configured root directory does not exist on disk.")
    if not policy_exists:
        hints.append("Policy file path is missing; fix ORCHESTRATOR_POLICY to a valid JSON policy path.")
    if policy_exists and not policy_loaded:
        hints.append("Policy failed to load; validate policy JSON schema and readability.")
    if agents and not active_agents:
        hints.append("No active agents detected; reconnect workers with orchestrator_connect_to_leader.")
    if not agents and not orch_available:
        hints.append("Orchestrator is unavailable in degraded mode; fix root/policy binding first.")
    if int(discovered.get("inferred_only_count", 0)) > 0:
        hints.append("Some agents are inferred-only; register/heartbeat them to establish identity.")

    for warning in server_binding.get("warnings", []):
        if isinstance(warning, str):
            hint = _hint_for_binding_warning(warning)
            if hint:
                hints.append(hint)

    for warning in runtime_source_consistency.get("warnings", []):
        if isinstance(warning, str) and warning.startswith("source_hash_mismatch"):
            hints.append("Server source changed after startup; restart MCP server to load current code.")
        if isinstance(warning, str) and warning.startswith("git_commit_mismatch"):
            hints.append("Git commit changed after startup; restart MCP server to align runtime and workspace.")

    for item in auth_failures:
        reason = str(item.get("reason", ""))
        hint = _hint_for_identity_reason(reason)
        if hint:
            hints.append(hint)

    check_results = [checks[name]["ok"] for name in checks]
    checks_passed = sum(1 for ok in check_results if ok)
    checks_total = len(check_results)
    overall_ok = checks_passed == checks_total

    return {
        "ok": overall_ok,
        "degraded_mode": not orch_available,
        "manager": manager,
        "roles": roles,
        "summary": {
            "checks_passed": checks_passed,
            "checks_total": checks_total,
            "registered_agents": len(agents),
            "active_agents": len(active_agents),
        },
        "checks": checks,
        "hints": _dedupe_keep_order(hints),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
