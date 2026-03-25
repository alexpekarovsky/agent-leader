"""PR-ready summary generator from task report data.

Converts orchestrator task + report records into GitHub PR description
markdown suitable for automated or manual PR creation workflows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def generate_pr_summary(
    *,
    task: Dict[str, Any],
    report: Dict[str, Any],
    changed_files: Optional[List[str]] = None,
) -> str:
    """Generate a markdown PR body from task and report data.

    Parameters
    ----------
    task:
        Task record dict with at minimum ``title``.  Optional keys used:
        ``acceptance_criteria``, ``tags``, ``delivery_profile``, ``id``.
    report:
        Report record dict with ``commit_sha``, ``test_summary``,
        and optionally ``artifacts``, ``notes``, ``status``.
    changed_files:
        Explicit list of changed file paths.  When *None* the function
        falls back to ``report["artifacts"]`` if present.

    Returns
    -------
    str
        Markdown-formatted PR description body.
    """
    sections: List[str] = []

    # -- Title / summary ----------------------------------------------------
    title = task.get("title", "Untitled task")
    task_id = task.get("id", "")
    sections.append("## Summary\n")
    if task_id:
        sections.append(f"**Task:** `{task_id}`\n")
    sections.append(f"{title}\n")

    # -- Acceptance criteria ------------------------------------------------
    criteria = task.get("acceptance_criteria") or []
    if criteria:
        lines = ["## Acceptance criteria\n"]
        for item in criteria:
            lines.append(f"- [ ] {item}")
        sections.append("\n".join(lines) + "\n")

    # -- Implementation notes -----------------------------------------------
    notes = report.get("notes")
    if notes:
        sections.append(f"## Implementation notes\n\n{notes}\n")

    # -- Test summary -------------------------------------------------------
    test_summary = report.get("test_summary") or {}
    if test_summary:
        passed = test_summary.get("passed", 0)
        failed = test_summary.get("failed", 0)
        total = passed + failed
        command = test_summary.get("command", "")

        lines = ["## Test summary\n"]
        lines.append("| Passed | Failed | Total |")
        lines.append("|--------|--------|-------|")
        lines.append(f"| {passed} | {failed} | {total} |")
        if command:
            lines.append(f"\n```\n{command}\n```")
        sections.append("\n".join(lines) + "\n")

    # -- Commit metrics -----------------------------------------------------
    commit_sha = report.get("commit_sha", "")
    if commit_sha:
        sections.append(f"## Commit\n\n`{commit_sha}`\n")

    # -- Changed files ------------------------------------------------------
    files = changed_files if changed_files is not None else report.get("artifacts")
    if files:
        lines = ["## Changed files\n"]
        for f in files:
            lines.append(f"- `{f}`")
        sections.append("\n".join(lines) + "\n")

    # -- Delivery profile ---------------------------------------------------
    profile = task.get("delivery_profile") or {}
    if profile:
        risk = profile.get("risk", "")
        test_plan = profile.get("test_plan", "")
        parts = []
        if risk:
            parts.append(f"**Risk:** {risk}")
        if test_plan:
            parts.append(f"**Test plan:** {test_plan}")
        if parts:
            sections.append("## Delivery profile\n\n" + " | ".join(parts) + "\n")

    return "\n".join(sections).rstrip() + "\n"
