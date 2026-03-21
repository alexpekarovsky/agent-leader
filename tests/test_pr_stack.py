"""Tests for stacked PR chain model and dependency gating."""

from __future__ import annotations

import pytest

from orchestrator.pr_stack import (
    PR_STATES,
    STACK_STATES,
    add_pr_to_stack,
    create_stack,
    get_next_ready_prs,
    is_pr_ready,
    process_close_event,
    process_merge_event,
    remove_pr_from_stack,
    update_pr_state,
)


# ---------------------------------------------------------------------------
# Stack creation
# ---------------------------------------------------------------------------


class TestCreateStack:
    def test_creates_valid_stack(self):
        stack = create_stack(repo="org/repo", title="Auth rewrite")
        assert stack["id"].startswith("STACK-")
        assert stack["repo"] == "org/repo"
        assert stack["title"] == "Auth rewrite"
        assert stack["base_branch"] == "main"
        assert stack["state"] == "open"
        assert stack["prs"] == []
        assert stack["task_ids"] == []

    def test_custom_base_branch(self):
        stack = create_stack(repo="org/repo", title="T", base_branch="develop")
        assert stack["base_branch"] == "develop"

    def test_task_ids_persisted(self):
        stack = create_stack(repo="org/repo", title="T", task_ids=["TASK-aaa", "TASK-bbb"])
        assert stack["task_ids"] == ["TASK-aaa", "TASK-bbb"]

    def test_created_by_recorded(self):
        stack = create_stack(repo="org/repo", title="T", created_by="claude_code")
        assert stack["created_by"] == "claude_code"


# ---------------------------------------------------------------------------
# Adding PRs to stack
# ---------------------------------------------------------------------------


class TestAddPrToStack:
    def _make_stack(self):
        return create_stack(repo="org/repo", title="Feature")

    def test_first_pr_targets_base_branch(self):
        stack = self._make_stack()
        pr = add_pr_to_stack(stack, branch="feat/step-1", title="Step 1")
        assert pr["base_branch"] == "main"
        assert pr["gated"] is False
        assert pr["state"] == "draft"
        assert len(stack["prs"]) == 1

    def test_second_pr_targets_first_branch(self):
        stack = self._make_stack()
        add_pr_to_stack(stack, branch="feat/step-1", title="Step 1")
        pr2 = add_pr_to_stack(stack, branch="feat/step-2", title="Step 2")
        assert pr2["base_branch"] == "feat/step-1"
        assert pr2["gated"] is True

    def test_three_pr_chain(self):
        stack = self._make_stack()
        add_pr_to_stack(stack, branch="feat/a", title="A")
        add_pr_to_stack(stack, branch="feat/b", title="B")
        pr3 = add_pr_to_stack(stack, branch="feat/c", title="C")
        assert pr3["base_branch"] == "feat/b"
        assert pr3["gated"] is True

    def test_insert_at_position(self):
        stack = self._make_stack()
        add_pr_to_stack(stack, branch="feat/a", title="A")
        add_pr_to_stack(stack, branch="feat/c", title="C")
        pr_b = add_pr_to_stack(stack, branch="feat/b", title="B", position=1)
        assert pr_b["base_branch"] == "feat/a"
        assert stack["prs"][1]["id"] == pr_b["id"]
        # C should now target B
        assert stack["prs"][2]["base_branch"] == "feat/b"

    def test_task_id_linked(self):
        stack = self._make_stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X", task_id="TASK-123")
        assert pr["task_id"] == "TASK-123"

    def test_pr_number_optional(self):
        stack = self._make_stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X", pr_number=42)
        assert pr["pr_number"] == 42


# ---------------------------------------------------------------------------
# Remove PR
# ---------------------------------------------------------------------------


class TestRemovePr:
    def test_remove_middle_pr_recomputes_bases(self):
        stack = create_stack(repo="org/repo", title="T")
        pr_a = add_pr_to_stack(stack, branch="feat/a", title="A")
        pr_b = add_pr_to_stack(stack, branch="feat/b", title="B")
        pr_c = add_pr_to_stack(stack, branch="feat/c", title="C")
        assert remove_pr_from_stack(stack, pr_b["id"]) is True
        assert len(stack["prs"]) == 2
        # C now targets A
        assert stack["prs"][1]["base_branch"] == "feat/a"

    def test_remove_nonexistent_returns_false(self):
        stack = create_stack(repo="org/repo", title="T")
        assert remove_pr_from_stack(stack, "STPR-nonexistent") is False


# ---------------------------------------------------------------------------
# Dependency gating
# ---------------------------------------------------------------------------


class TestDependencyGating:
    def _build_stack(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="PR 1")
        pr2 = add_pr_to_stack(stack, branch="feat/2", title="PR 2")
        pr3 = add_pr_to_stack(stack, branch="feat/3", title="PR 3")
        return stack, pr1, pr2, pr3

    def test_first_pr_always_ready(self):
        stack, pr1, pr2, pr3 = self._build_stack()
        assert is_pr_ready(stack, pr1["id"]) is True

    def test_second_pr_gated_before_parent_merge(self):
        stack, pr1, pr2, pr3 = self._build_stack()
        assert is_pr_ready(stack, pr2["id"]) is False

    def test_second_pr_ready_after_parent_merge(self):
        stack, pr1, pr2, pr3 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        assert is_pr_ready(stack, pr2["id"]) is True

    def test_third_pr_still_gated_after_first_merge(self):
        stack, pr1, pr2, pr3 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        assert is_pr_ready(stack, pr3["id"]) is False

    def test_third_pr_ready_after_sequential_merges(self):
        stack, pr1, pr2, pr3 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        process_merge_event(stack, pr2["id"])
        assert is_pr_ready(stack, pr3["id"]) is True

    def test_nonexistent_pr_not_ready(self):
        stack, _, _, _ = self._build_stack()
        assert is_pr_ready(stack, "STPR-ghost") is False


# ---------------------------------------------------------------------------
# Merge events
# ---------------------------------------------------------------------------


class TestMergeEvents:
    def _build_stack(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="PR 1")
        pr2 = add_pr_to_stack(stack, branch="feat/2", title="PR 2")
        return stack, pr1, pr2

    def test_merge_sets_state_and_timestamp(self):
        stack, pr1, pr2 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        assert stack["prs"][0]["state"] == "merged"
        assert stack["prs"][0]["merged_at"] is not None

    def test_merge_ungates_child(self):
        stack, pr1, pr2 = self._build_stack()
        ungated = process_merge_event(stack, pr1["id"])
        assert len(ungated) == 1
        assert ungated[0]["id"] == pr2["id"]
        assert stack["prs"][1]["gated"] is False

    def test_merge_last_pr_returns_no_children(self):
        stack, pr1, pr2 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        ungated = process_merge_event(stack, pr2["id"])
        assert ungated == []

    def test_full_merge_sets_stack_merged(self):
        stack, pr1, pr2 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        process_merge_event(stack, pr2["id"])
        assert stack["state"] == "merged"

    def test_partial_merge_sets_partially_merged(self):
        stack, pr1, pr2 = self._build_stack()
        process_merge_event(stack, pr1["id"])
        assert stack["state"] == "partially_merged"


# ---------------------------------------------------------------------------
# Close events
# ---------------------------------------------------------------------------


class TestCloseEvents:
    def test_close_sets_pr_state(self):
        stack = create_stack(repo="org/repo", title="T")
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        process_close_event(stack, pr["id"])
        assert stack["prs"][0]["state"] == "closed"

    def test_all_closed_sets_stack_closed(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="1")
        pr2 = add_pr_to_stack(stack, branch="feat/2", title="2")
        process_close_event(stack, pr1["id"])
        process_close_event(stack, pr2["id"])
        assert stack["state"] == "closed"


# ---------------------------------------------------------------------------
# get_next_ready_prs
# ---------------------------------------------------------------------------


class TestGetNextReadyPrs:
    def test_empty_stack(self):
        stack = create_stack(repo="org/repo", title="T")
        assert get_next_ready_prs(stack) == []

    def test_returns_first_pr_when_open(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="1")
        add_pr_to_stack(stack, branch="feat/2", title="2")
        ready = get_next_ready_prs(stack)
        assert len(ready) == 1
        assert ready[0]["id"] == pr1["id"]

    def test_returns_second_after_first_merged(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="1")
        pr2 = add_pr_to_stack(stack, branch="feat/2", title="2")
        process_merge_event(stack, pr1["id"])
        ready = get_next_ready_prs(stack)
        assert len(ready) == 1
        assert ready[0]["id"] == pr2["id"]

    def test_returns_empty_when_all_merged(self):
        stack = create_stack(repo="org/repo", title="T")
        pr1 = add_pr_to_stack(stack, branch="feat/1", title="1")
        pr2 = add_pr_to_stack(stack, branch="feat/2", title="2")
        process_merge_event(stack, pr1["id"])
        process_merge_event(stack, pr2["id"])
        assert get_next_ready_prs(stack) == []


# ---------------------------------------------------------------------------
# update_pr_state
# ---------------------------------------------------------------------------


class TestUpdatePrState:
    def test_update_state(self):
        stack = create_stack(repo="org/repo", title="T")
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        result = update_pr_state(stack, pr["id"], state="open")
        assert result is not None
        assert result["state"] == "open"

    def test_update_ci_status(self):
        stack = create_stack(repo="org/repo", title="T")
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        result = update_pr_state(stack, pr["id"], ci_status="passed")
        assert result["ci_status"] == "passed"

    def test_update_pr_number(self):
        stack = create_stack(repo="org/repo", title="T")
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        result = update_pr_state(stack, pr["id"], pr_number=99)
        assert result["pr_number"] == 99

    def test_update_nonexistent_returns_none(self):
        stack = create_stack(repo="org/repo", title="T")
        assert update_pr_state(stack, "STPR-ghost", state="open") is None

    def test_invalid_state_ignored(self):
        stack = create_stack(repo="org/repo", title="T")
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        result = update_pr_state(stack, pr["id"], state="banana")
        assert result["state"] == "draft"  # unchanged


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


class TestConstants:
    def test_pr_states(self):
        assert "draft" in PR_STATES
        assert "merged" in PR_STATES

    def test_stack_states(self):
        assert "open" in STACK_STATES
        assert "merged" in STACK_STATES
