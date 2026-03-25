"""Stacked PR chain model and dependency gating.

Defines the data model for PR stacks (ordered chains of dependent pull
requests) and provides helpers for lifecycle management:

- Creating stacks with ordered PR entries
- Adding/removing PRs from a stack
- Querying merge-readiness based on parent PR status
- Reacting to merge events to ungate children
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PR_STATES = {"draft", "open", "approved", "merged", "closed"}
STACK_STATES = {"open", "partially_merged", "merged", "closed"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Stack CRUD
# ---------------------------------------------------------------------------

def create_stack(
    *,
    repo: str,
    title: str,
    task_ids: Optional[List[str]] = None,
    base_branch: str = "main",
    created_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new empty PR stack definition."""
    return {
        "id": _gen_id("STACK"),
        "repo": repo,
        "title": title,
        "base_branch": base_branch,
        "state": "open",
        "task_ids": list(task_ids or []),
        "prs": [],
        "created_by": created_by,
        "created_at": _now(),
        "updated_at": _now(),
    }


def add_pr_to_stack(
    stack: Dict[str, Any],
    *,
    branch: str,
    title: str,
    task_id: Optional[str] = None,
    pr_number: Optional[int] = None,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Append (or insert at *position*) a PR entry in the stack.

    The PR's ``base_branch`` is automatically set:
    - First PR in the stack targets ``stack["base_branch"]``
    - Subsequent PRs target the branch of the preceding PR

    Returns the new PR entry dict.
    """
    prs = stack["prs"]
    idx = position if position is not None else len(prs)
    idx = max(0, min(idx, len(prs)))

    # Determine the base for this PR.
    if idx == 0:
        pr_base = stack["base_branch"]
    else:
        pr_base = prs[idx - 1]["branch"]

    pr_entry: Dict[str, Any] = {
        "id": _gen_id("STPR"),
        "stack_id": stack["id"],
        "branch": branch,
        "base_branch": pr_base,
        "title": title,
        "task_id": task_id,
        "pr_number": pr_number,
        "state": "draft",
        "ci_status": None,
        "gated": idx > 0,  # first PR is never gated
        "created_at": _now(),
        "updated_at": _now(),
        "merged_at": None,
    }

    prs.insert(idx, pr_entry)

    # Fix up base_branch pointers for everything after the insertion.
    _recompute_bases(stack)

    stack["updated_at"] = _now()
    return pr_entry


def remove_pr_from_stack(stack: Dict[str, Any], pr_id: str) -> bool:
    """Remove a PR entry by id.  Returns True if found and removed."""
    before = len(stack["prs"])
    stack["prs"] = [p for p in stack["prs"] if p["id"] != pr_id]
    if len(stack["prs"]) < before:
        _recompute_bases(stack)
        stack["updated_at"] = _now()
        return True
    return False


# ---------------------------------------------------------------------------
# Dependency gating
# ---------------------------------------------------------------------------

def is_pr_ready(stack: Dict[str, Any], pr_id: str) -> bool:
    """Check whether a PR in the stack is unblocked (all parents merged)."""
    for i, pr in enumerate(stack["prs"]):
        if pr["id"] == pr_id:
            if i == 0:
                return True  # first in chain — always ready
            parent = stack["prs"][i - 1]
            return parent["state"] == "merged"
    return False


def get_next_ready_prs(stack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return PRs that are unblocked but not yet merged/closed."""
    ready = []
    for i, pr in enumerate(stack["prs"]):
        if pr["state"] in ("merged", "closed"):
            continue
        if i == 0 or stack["prs"][i - 1]["state"] == "merged":
            ready.append(pr)
            break  # only the first unmerged-and-ready PR
    return ready


def process_merge_event(
    stack: Dict[str, Any],
    pr_id: str,
) -> List[Dict[str, Any]]:
    """Mark a PR as merged and return newly-ungated child PRs.

    Also updates the stack-level state:
    - All PRs merged → stack state = "merged"
    - Some merged → "partially_merged"
    """
    ungated: List[Dict[str, Any]] = []
    now = _now()

    for i, pr in enumerate(stack["prs"]):
        if pr["id"] == pr_id:
            pr["state"] = "merged"
            pr["merged_at"] = now
            pr["gated"] = False
            pr["updated_at"] = now

            # Ungate the next PR in the chain if it exists.
            if i + 1 < len(stack["prs"]):
                child = stack["prs"][i + 1]
                if child["state"] not in ("merged", "closed"):
                    child["gated"] = False
                    child["updated_at"] = now
                    ungated.append(child)
            break

    # Update stack-level state.
    _update_stack_state(stack)
    stack["updated_at"] = now
    return ungated


def process_close_event(
    stack: Dict[str, Any],
    pr_id: str,
) -> None:
    """Mark a PR as closed (without merge).  Downstream PRs stay gated."""
    now = _now()
    for pr in stack["prs"]:
        if pr["id"] == pr_id:
            pr["state"] = "closed"
            pr["updated_at"] = now
            break
    _update_stack_state(stack)
    stack["updated_at"] = now


def update_pr_state(
    stack: Dict[str, Any],
    pr_id: str,
    *,
    state: Optional[str] = None,
    ci_status: Optional[str] = None,
    pr_number: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Update mutable fields on a PR entry.  Returns the updated entry or None."""
    for pr in stack["prs"]:
        if pr["id"] == pr_id:
            if state is not None and state in PR_STATES:
                pr["state"] = state
            if ci_status is not None:
                pr["ci_status"] = ci_status
            if pr_number is not None:
                pr["pr_number"] = pr_number
            pr["updated_at"] = _now()
            _update_stack_state(stack)
            stack["updated_at"] = _now()
            return pr
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recompute_bases(stack: Dict[str, Any]) -> None:
    """Recompute base_branch and gated flags for all PRs in order."""
    for i, pr in enumerate(stack["prs"]):
        if i == 0:
            pr["base_branch"] = stack["base_branch"]
            pr["gated"] = False
        else:
            pr["base_branch"] = stack["prs"][i - 1]["branch"]
            parent = stack["prs"][i - 1]
            pr["gated"] = parent["state"] != "merged"


def _update_stack_state(stack: Dict[str, Any]) -> None:
    """Derive stack-level state from PR states."""
    prs = stack["prs"]
    if not prs:
        stack["state"] = "open"
        return
    all_terminal = all(p["state"] in ("merged", "closed") for p in prs)
    any_merged = any(p["state"] == "merged" for p in prs)
    all_closed = all(p["state"] == "closed" for p in prs)
    all_merged = all(p["state"] == "merged" for p in prs)

    if all_merged:
        stack["state"] = "merged"
    elif all_closed:
        stack["state"] = "closed"
    elif all_terminal:
        # Mix of merged + closed
        stack["state"] = "closed"
    elif any_merged:
        stack["state"] = "partially_merged"
    else:
        stack["state"] = "open"
