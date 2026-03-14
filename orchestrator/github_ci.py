"""GitHub CI normalization helpers.

Initial building block for CI ingestion workflows. Converts raw check-run /
workflow payload fragments into a compact, orchestration-friendly summary.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_github_ci_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize GitHub CI/check payload into a stable summary.

    Expected loose input compatibility:
    - check_run webhook fragments
    - workflow_job fragments
    - custom reduced CI payloads
    """
    status = str(payload.get("status") or "").strip().lower() or "unknown"
    conclusion = str(payload.get("conclusion") or "").strip().lower() or "unknown"
    name = str(payload.get("name") or payload.get("workflow") or "ci").strip()
    html_url = str(payload.get("html_url") or payload.get("url") or "").strip()
    sha = str(payload.get("head_sha") or payload.get("sha") or "").strip()
    branch = str(payload.get("head_branch") or payload.get("branch") or "").strip()
    run_id = _safe_int(payload.get("run_id") or payload.get("id"))
    attempt = _safe_int(payload.get("run_attempt") or payload.get("attempt"))
    passed = _safe_int(payload.get("passed"))
    failed = _safe_int(payload.get("failed"))

    # Derived status used by orchestrator reporting.
    if conclusion in {"success", "neutral", "skipped"}:
        ci_state = "passed"
    elif conclusion in {"failure", "cancelled", "timed_out", "action_required"}:
        ci_state = "failed"
    elif status in {"queued", "in_progress", "requested", "waiting"}:
        ci_state = "running"
    else:
        ci_state = "unknown"

    return {
        "provider": "github",
        "name": name,
        "state": ci_state,
        "status": status,
        "conclusion": conclusion,
        "run_id": run_id,
        "attempt": attempt,
        "sha": sha or None,
        "branch": branch or None,
        "url": html_url or None,
        "passed": passed,
        "failed": failed,
    }
