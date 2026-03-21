"""Integration tests for PR stack engine methods and event publishing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


@pytest.fixture()
def engine(tmp_path):
    policy = _make_policy(tmp_path / "policy.json")
    orch = Orchestrator(root=tmp_path, policy=policy)
    orch.bootstrap()
    return orch


class TestCreatePrStack:
    def test_creates_and_persists(self, engine):
        stack = engine.create_pr_stack(
            repo="org/repo",
            title="Auth rewrite",
            task_ids=["TASK-aaa"],
            created_by="claude_code",
        )
        assert stack["id"].startswith("STACK-")
        assert stack["state"] == "open"

        # Verify persistence
        stacks = engine.get_pr_stacks()
        assert len(stacks) == 1
        assert stacks[0]["id"] == stack["id"]

    def test_emits_event(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        events = list(engine.bus.iter_events())
        prstack_events = [e for e in events if e.get("type") == "prstack.created"]
        assert len(prstack_events) >= 1
        assert prstack_events[-1]["payload"]["stack_id"] == stack["id"]


class TestAddPrToStack:
    def test_add_and_persist(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr = engine.add_pr_to_stack(
            stack["id"],
            branch="feat/step-1",
            title="Step 1",
            task_id="TASK-bbb",
        )
        assert pr["id"].startswith("STPR-")
        assert pr["branch"] == "feat/step-1"

        # Verify in persisted state
        stacks = engine.get_pr_stacks()
        assert len(stacks[0]["prs"]) == 1

    def test_raises_on_missing_stack(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.add_pr_to_stack("STACK-nonexistent", branch="x", title="X")

    def test_emits_event(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr = engine.add_pr_to_stack(stack["id"], branch="feat/x", title="X")
        events = list(engine.bus.iter_events())
        added_events = [e for e in events if e.get("type") == "prstack.pr_added"]
        assert len(added_events) >= 1
        assert added_events[-1]["payload"]["pr_id"] == pr["id"]


class TestProcessPrStackMerge:
    def _setup_stack(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr1 = engine.add_pr_to_stack(stack["id"], branch="feat/1", title="1")
        pr2 = engine.add_pr_to_stack(stack["id"], branch="feat/2", title="2")
        return stack, pr1, pr2

    def test_merge_ungates_child(self, engine):
        stack, pr1, pr2 = self._setup_stack(engine)
        result = engine.process_pr_stack_merge(stack["id"], pr1["id"])
        assert result["stack_state"] == "partially_merged"
        assert len(result["ungated_prs"]) == 1
        assert result["ungated_prs"][0]["id"] == pr2["id"]

    def test_full_merge_emits_stack_merged(self, engine):
        stack, pr1, pr2 = self._setup_stack(engine)
        engine.process_pr_stack_merge(stack["id"], pr1["id"])
        engine.process_pr_stack_merge(stack["id"], pr2["id"])
        events = list(engine.bus.iter_events())
        merged_events = [e for e in events if e.get("type") == "prstack.merged"]
        assert len(merged_events) >= 1

    def test_raises_on_missing_stack(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.process_pr_stack_merge("STACK-ghost", "STPR-ghost")

    def test_persists_merge_state(self, engine):
        stack, pr1, pr2 = self._setup_stack(engine)
        engine.process_pr_stack_merge(stack["id"], pr1["id"])
        stacks = engine.get_pr_stacks()
        assert stacks[0]["prs"][0]["state"] == "merged"


class TestGetPrStacks:
    def test_filter_by_repo(self, engine):
        engine.create_pr_stack(repo="org/a", title="A")
        engine.create_pr_stack(repo="org/b", title="B")
        result = engine.get_pr_stacks(repo="org/a")
        assert len(result) == 1
        assert result[0]["repo"] == "org/a"

    def test_filter_by_state(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        pr = engine.add_pr_to_stack(stack["id"], branch="feat/x", title="X")
        engine.process_pr_stack_merge(stack["id"], pr["id"])
        open_stacks = engine.get_pr_stacks(state="open")
        merged_stacks = engine.get_pr_stacks(state="merged")
        assert len(merged_stacks) == 1
        assert len(open_stacks) == 0


class TestGetStackStatus:
    def test_status_summary(self, engine):
        stack = engine.create_pr_stack(repo="org/repo", title="T")
        engine.add_pr_to_stack(stack["id"], branch="feat/1", title="1")
        engine.add_pr_to_stack(stack["id"], branch="feat/2", title="2")
        status = engine.get_stack_status(stack["id"])
        assert status["total_prs"] == 2
        assert status["merged_count"] == 0
        assert status["gated_count"] == 1  # second PR is gated
        assert len(status["next_ready"]) == 1

    def test_raises_on_missing_stack(self, engine):
        with pytest.raises(ValueError, match="PR stack not found"):
            engine.get_stack_status("STACK-nope")
