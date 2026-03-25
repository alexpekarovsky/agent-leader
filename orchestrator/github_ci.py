"""GitHub CI normalization helpers.

Initial building block for CI ingestion workflows. Converts raw check-run /
workflow payload fragments into a compact, orchestration-friendly summary.
Also provides utilities for creating GitHub issues from orchestrator bug records.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
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

    ci_logs = []
    log_url = str(payload.get("output", {}).get("log_url") or payload.get("log_url") or "").strip()
    if log_url:
        ci_logs.append(log_url)

    # ci_logs might also be a list of urls
    if isinstance(payload.get("ci_logs"), list):
        for log in payload.get("ci_logs"):
            if isinstance(log, str) and log.strip():
                ci_logs.append(log.strip())

    ci_artifacts = []
    raw_artifacts = payload.get("artifacts")
    if isinstance(raw_artifacts, list):
        for item in raw_artifacts:
            if isinstance(item, dict) and item.get("name") and item.get("url"):
                ci_artifacts.append({
                    "name": str(item["name"]).strip(),
                    "url": str(item["url"]).strip(),
                })

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
        "ci_logs": sorted(list(set(ci_logs))) if ci_logs else None,
        "ci_artifacts": ci_artifacts if ci_artifacts else None,
    }


# ---------------------------------------------------------------------------
# GitHub issue creation from orchestrator bug records
# ---------------------------------------------------------------------------

_SEVERITY_LABEL_MAP: Dict[str, str] = {
    "critical": "severity:critical",
    "high": "severity:high",
    "medium": "severity:medium",
    "low": "severity:low",
}


def build_github_issue_payload(bug: Dict[str, Any]) -> Dict[str, Any]:
    """Build a GitHub-compatible issue payload from an orchestrator bug record.

    Returns a dict with ``title``, ``body``, ``labels``, and ``assignees``
    ready to POST to ``/repos/{owner}/{repo}/issues``.
    """
    bug_id = bug.get("id", "UNKNOWN_BUG")
    source_task = bug.get("source_task", "UNKNOWN_TASK")
    owner = bug.get("owner", "UNKNOWN_OWNER")
    severity = bug.get("severity", "medium")
    repro_steps = bug.get("repro_steps", "No reproduction steps provided.")
    expected = bug.get("expected", "Expected behavior not specified.")
    actual = bug.get("actual", "Actual behavior not specified.")

    title = f"[{severity.upper()} Bug] Task {source_task}: {actual}"

    body = (
        f"**Bug ID:** {bug_id}\n"
        f"**Task ID:** {source_task}\n"
        f"**Owner:** {owner}\n"
        f"**Severity:** {severity}\n\n"
        f"**Reproduction Steps:**\n```\n{repro_steps}\n```\n\n"
        f"**Expected Behavior:**\n```\n{expected}\n```\n\n"
        f"**Actual Behavior:**\n```\n{actual}\n```\n"
    )

    severity_label = _SEVERITY_LABEL_MAP.get(severity, f"severity:{severity}")
    labels = [severity_label, "bug", f"task:{source_task}"]
    assignees = [owner]

    return {
        "title": title,
        "body": body,
        "labels": labels,
        "assignees": assignees,
    }


def post_github_issue(
    repo: str,
    token: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """POST an issue to the GitHub API and return the response.

    ``repo`` is ``owner/repo`` format.  ``payload`` should be the dict
    returned by :func:`build_github_issue_payload`.

    Returns the parsed JSON response from the GitHub API.
    Raises on HTTP errors.
    """
    url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())
