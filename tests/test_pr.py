"""Tests for PR stack model, engine integration, and PR summary generation."""

from __future__ import annotations

import json

import pytest

from orchestrator.pr_stack import (
    add_pr_to_stack,
    create_stack,
    get_next_ready_prs,
    is_pr_ready,
    process_close_event,
    process_merge_event,
    remove_pr_from_stack,
    update_pr_state,
)
from orchestrator.pr_summary import generate_pr_summary
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _stack(**kw):
    kw.setdefault("repo", "org/repo")
    kw.setdefault("title", "Feature")
    return create_stack(**kw)


def _stack_with_prs(n=3):
    stack = _stack()
    prs = [add_pr_to_stack(stack, branch=f"feat/{i+1}", title=f"PR {i+1}") for i in range(n)]
    return stack, prs


@pytest.fixture()
def engine(tmp_path):
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    (tmp_path / "policy.json").write_text(json.dumps(raw), encoding="utf-8")
    policy = Policy.load(tmp_path / "policy.json")
    orch = Orchestrator(root=tmp_path, policy=policy)
    orch.bootstrap()
    return orch


# --- PR Stack model layer ---

class TestCreateStack:
    def test_creates_valid_stack(self):
        stack = _stack(title="Auth rewrite")
        assert stack["id"].startswith("STACK-")
        assert stack["repo"] == "org/repo"
        assert stack["title"] == "Auth rewrite"
        assert stack["base_branch"] == "main"
        assert stack["state"] == "open"
        assert stack["prs"] == []

    def test_optional_fields(self):
        stack = create_stack(repo="org/repo", title="T", base_branch="develop",
                             task_ids=["TASK-aaa"], created_by="claude_code")
        assert stack["base_branch"] == "develop"
        assert stack["task_ids"] == ["TASK-aaa"]
        assert stack["created_by"] == "claude_code"

class TestAddPr:
    def test_first_pr_targets_base_branch(self):
        stack = _stack()
        pr = add_pr_to_stack(stack, branch="feat/step-1", title="Step 1")
        assert pr["base_branch"] == "main"
        assert pr["gated"] is False
        assert pr["state"] == "draft"

    def test_chained_prs_target_predecessor(self):
        stack = _stack()
        add_pr_to_stack(stack, branch="feat/a", title="A")
        pr2 = add_pr_to_stack(stack, branch="feat/b", title="B")
        pr3 = add_pr_to_stack(stack, branch="feat/c", title="C")
        assert pr2["base_branch"] == "feat/a"
        assert pr2["gated"] is True
        assert pr3["base_branch"] == "feat/b"

    def test_insert_at_position_recomputes_bases(self):
        stack = _stack()
        add_pr_to_stack(stack, branch="feat/a", title="A")
        add_pr_to_stack(stack, branch="feat/c", title="C")
        pr_b = add_pr_to_stack(stack, branch="feat/b", title="B", position=1)
        assert pr_b["base_branch"] == "feat/a"
        assert stack["prs"][2]["base_branch"] == "feat/b"

    def test_optional_metadata(self):
        stack = _stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X", task_id="TASK-123", pr_number=42)
        assert pr["task_id"] == "TASK-123"
        assert pr["pr_number"] == 42

class TestRemovePr:
    def test_remove_middle_recomputes_bases(self):
        stack, prs = _stack_with_prs(3)
        assert remove_pr_from_stack(stack, prs[1]["id"]) is True
        assert len(stack["prs"]) == 2
        assert stack["prs"][1]["base_branch"] == "feat/1"

    def test_remove_nonexistent_returns_false(self):
        stack = _stack()
        assert remove_pr_from_stack(stack, "STPR-nonexistent") is False

class TestDependencyGating:
    def test_first_pr_always_ready(self):
        stack, prs = _stack_with_prs(3)
        assert is_pr_ready(stack, prs[0]["id"]) is True

    def test_gated_until_parent_merges(self):
        stack, prs = _stack_with_prs(3)
        assert is_pr_ready(stack, prs[1]["id"]) is False
        process_merge_event(stack, prs[0]["id"])
        assert is_pr_ready(stack, prs[1]["id"]) is True
        assert is_pr_ready(stack, prs[2]["id"]) is False

    def test_sequential_merges_ungate_all(self):
        stack, prs = _stack_with_prs(3)
        process_merge_event(stack, prs[0]["id"])
        process_merge_event(stack, prs[1]["id"])
        assert is_pr_ready(stack, prs[2]["id"]) is True

    def test_nonexistent_pr_not_ready(self):
        stack, _ = _stack_with_prs(2)
        assert is_pr_ready(stack, "STPR-ghost") is False

class TestMergeEvents:
    def test_merge_sets_state_and_ungates_child(self):
        stack, prs = _stack_with_prs(2)
        ungated = process_merge_event(stack, prs[0]["id"])
        assert stack["prs"][0]["state"] == "merged"
        assert stack["prs"][0]["merged_at"] is not None
        assert len(ungated) == 1
        assert ungated[0]["id"] == prs[1]["id"]
        assert stack["prs"][1]["gated"] is False

    def test_full_merge_sets_stack_merged(self):
        stack, prs = _stack_with_prs(2)
        process_merge_event(stack, prs[0]["id"])
        assert stack["state"] == "partially_merged"
        process_merge_event(stack, prs[1]["id"])
        assert stack["state"] == "merged"

    def test_merge_last_returns_no_children(self):
        stack, prs = _stack_with_prs(2)
        process_merge_event(stack, prs[0]["id"])
        assert process_merge_event(stack, prs[1]["id"]) == []

class TestCloseEvents:
    def test_close_sets_pr_and_stack_state(self):
        stack, prs = _stack_with_prs(2)
        process_close_event(stack, prs[0]["id"])
        assert stack["prs"][0]["state"] == "closed"
        process_close_event(stack, prs[1]["id"])
        assert stack["state"] == "closed"

class TestGetNextReady:
    def test_empty_stack(self):
        assert get_next_ready_prs(_stack()) == []

    def test_returns_first_then_advances(self):
        stack, prs = _stack_with_prs(2)
        ready = get_next_ready_prs(stack)
        assert len(ready) == 1 and ready[0]["id"] == prs[0]["id"]
        process_merge_event(stack, prs[0]["id"])
        ready = get_next_ready_prs(stack)
        assert len(ready) == 1 and ready[0]["id"] == prs[1]["id"]

    def test_empty_when_all_merged(self):
        stack, prs = _stack_with_prs(2)
        for pr in prs:
            process_merge_event(stack, pr["id"])
        assert get_next_ready_prs(stack) == []

class TestUpdatePrState:
    def test_update_state_and_ci(self):
        stack = _stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        r = update_pr_state(stack, pr["id"], state="open")
        assert r["state"] == "open"
        r = update_pr_state(stack, pr["id"], ci_status="passed")
        assert r["ci_status"] == "passed"

    def test_update_pr_number(self):
        stack = _stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        r = update_pr_state(stack, pr["id"], pr_number=99)
        assert r["pr_number"] == 99

    def test_nonexistent_returns_none(self):
        assert update_pr_state(_stack(), "STPR-ghost", state="open") is None

    def test_invalid_state_ignored(self):
        stack = _stack()
        pr = add_pr_to_stack(stack, branch="feat/x", title="X")
        r = update_pr_state(stack, pr["id"], state="banana")
        assert r["state"] == "draft"

# --- PR Stack engine integration ---

class TestEngineStack:
    def test_create_persists_and_emits_event(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="Auth rewrite",
                                       task_ids=["TASK-aaa"], created_by="claude_code")
        assert stack["id"].startswith("STACK-")
        stacks = engine.get_pr_stacks()
        assert len(stacks) == 1 and stacks[0]["id"] == stack["id"]
        events = [e for e in engine.bus.iter_events() if e.get("type") == "prstack.created"]
        assert events and events[-1]["payload"]["stack_id"] == stack["id"]

    def test_add_pr_persists_and_emits_event(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr = engine.add_pr_to_stack(stack["id"], branch="feat/step-1", title="Step 1", task_id="TASK-bbb")
        assert pr["id"].startswith("STPR-")
        assert len(engine.get_pr_stacks()[0]["prs"]) == 1
        events = [e for e in engine.bus.iter_events() if e.get("type") == "prstack.pr_added"]
        assert events and events[-1]["payload"]["pr_id"] == pr["id"]

    def test_add_pr_to_missing_stack_raises(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.add_pr_to_stack("STACK-nonexistent", branch="x", title="X")

    def test_merge_ungates_and_persists(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr1 = engine.add_pr_to_stack(stack["id"], branch="feat/1", title="1")
        pr2 = engine.add_pr_to_stack(stack["id"], branch="feat/2", title="2")
        result = engine.process_pr_stack_merge(stack["id"], pr1["id"])
        assert result["stack_state"] == "partially_merged"
        assert result["ungated_prs"][0]["id"] == pr2["id"]
        assert engine.get_pr_stacks()[0]["prs"][0]["state"] == "merged"

    def test_full_merge_emits_stack_merged(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr1 = engine.add_pr_to_stack(stack["id"], branch="feat/1", title="1")
        pr2 = engine.add_pr_to_stack(stack["id"], branch="feat/2", title="2")
        engine.process_pr_stack_merge(stack["id"], pr1["id"])
        engine.process_pr_stack_merge(stack["id"], pr2["id"])
        events = [e for e in engine.bus.iter_events() if e.get("type") == "prstack.merged"]
        assert len(events) >= 1

    def test_merge_missing_stack_raises(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.process_pr_stack_merge("STACK-ghost", "STPR-ghost")

    def test_filter_by_repo_and_state(self, engine):
        engine.create_pr_stack(repo="org/a", title="A")
        engine.create_pr_stack(repo="org/b", title="B")
        assert len(engine.get_pr_stacks(repo="org/a")) == 1
        stack = engine.create_pr_stack(repo="org/c", title="C")
        pr = engine.add_pr_to_stack(stack["id"], branch="feat/x", title="X")
        engine.process_pr_stack_merge(stack["id"], pr["id"])
        assert len(engine.get_pr_stacks(state="merged")) == 1

    def test_stack_status_summary(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        engine.add_pr_to_stack(stack["id"], branch="feat/1", title="1")
        engine.add_pr_to_stack(stack["id"], branch="feat/2", title="2")
        status = engine.get_stack_status(stack["id"])
        assert status["total_prs"] == 2
        assert status["merged_count"] == 0
        assert status["gated_count"] == 1
        assert len(status["next_ready"]) == 1

    def test_stack_status_missing_raises(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.get_stack_status("STACK-nope")

# --- PR Summary generation ---

SAMPLE_TASK = {
    "id": "TASK-abcd1234",
    "title": "Add user authentication endpoint",
    "acceptance_criteria": [
        "POST /auth/login returns JWT token",
        "Invalid credentials return 401",
        "Test covers happy and error paths",
    ],
    "tags": ["backend", "auth"],
    "delivery_profile": {"risk": "medium", "test_plan": "targeted", "doc_impact": "none"},
}

SAMPLE_REPORT = {
    "task_id": "TASK-abcd1234",
    "agent": "claude_code",
    "commit_sha": "a1b2c3d4e5f6",
    "status": "done",
    "test_summary": {"command": ".venv/bin/python -m pytest tests/ -v", "passed": 42, "failed": 0},
    "artifacts": ["src/auth.py", "tests/test_auth.py"],
    "notes": "Implemented JWT-based login with bcrypt password hashing.",
}


class TestPrSummary:
    def test_full_summary(self):
        md = generate_pr_summary(task=SAMPLE_TASK, report=SAMPLE_REPORT)
        for section in ("## Summary", "## Acceptance criteria", "## Implementation notes",
                        "## Test summary", "## Commit", "## Changed files", "## Delivery profile"):
            assert section in md
        assert "`TASK-abcd1234`" in md
        assert "- [ ] POST /auth/login returns JWT token" in md
        assert "JWT-based login" in md
        assert "| 42 | 0 | 42 |" in md
        assert "`a1b2c3d4e5f6`" in md
        assert "- `src/auth.py`" in md
        assert "**Risk:** medium" in md

    def test_minimal_inputs(self):
        md = generate_pr_summary(task={"title": "Quick fix"},
                                 report={"commit_sha": "deadbeef", "status": "done"})
        assert "## Summary" in md and "Quick fix" in md
        for absent in ("## Acceptance criteria", "## Implementation notes", "## Changed files"):
            assert absent not in md

    def test_changed_files_override(self):
        md = generate_pr_summary(task=SAMPLE_TASK, report=SAMPLE_REPORT,
                                 changed_files=["README.md", "docs/api.md"])
        assert "- `README.md`" in md
        assert "src/auth.py" not in md

    def test_empty_artifacts_no_section(self):
        report = {**SAMPLE_REPORT, "artifacts": []}
        md = generate_pr_summary(task=SAMPLE_TASK, report=report, changed_files=[])
        assert "## Changed files" not in md

    def test_failures_in_table(self):
        report = {**SAMPLE_REPORT, "test_summary": {"command": "pytest", "passed": 10, "failed": 3}}
        md = generate_pr_summary(task=SAMPLE_TASK, report=report)
        assert "| 10 | 3 | 13 |" in md

    def test_no_delivery_profile(self):
        md = generate_pr_summary(task={"title": "Bare", "id": "TASK-0"}, report=SAMPLE_REPORT)
        assert "## Delivery profile" not in md

    def test_output_ends_with_single_newline(self):
        md = generate_pr_summary(task=SAMPLE_TASK, report=SAMPLE_REPORT)
        assert md.endswith("\n") and not md.endswith("\n\n")
