"""Consolidated tests for orchestrator status, agent identity, and metadata."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ── Shared helpers ────────────────────────────────────────────────────

def _make_orch(root: Path) -> Orchestrator:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    p = root / "policy.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    orch = Orchestrator(root=root, policy=Policy.load(p))
    orch.bootstrap()
    return orch


def _register(orch: Orchestrator, agent: str, **extra) -> dict:
    meta = {
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": "false",
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    }
    meta.update(extra)
    return orch.register_agent(agent, metadata=meta)


def _make_stale(orch: Orchestrator, agent: str) -> None:
    data = orch._read_json(orch.agents_path)
    if agent in data:
        data[agent]["last_seen"] = "2020-01-01T00:00:00+00:00"
        orch._write_json(orch.agents_path, data)


class _OrchestratorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ── Status tests ──────────────────────────────────────────────────────

CANONICAL_STATUS_FIELDS = {
    "timestamp", "manager", "roles", "task_count", "task_status_counts",
    "team_lane_counters", "bug_count", "in_progress", "wingman_count",
    "recovery_actions", "active_agents", "active_agent_identities", "metrics",
}


class StatusTests(_OrchestratorTestCase):
    """Canonical status fields and status counter behaviour."""

    def test_canonical_field_types_contract(self) -> None:
        expected = {
            "timestamp": str, "manager": (str, type(None)), "roles": dict,
            "task_count": int, "task_status_counts": dict,
            "team_lane_counters": dict, "bug_count": int, "in_progress": list,
            "wingman_count": int, "recovery_actions": list,
            "active_agents": list, "active_agent_identities": list, "metrics": dict,
        }
        self.assertEqual(set(expected.keys()), CANONICAL_STATUS_FIELDS)

    def test_mcp_payload_contains_canonical_fields(self) -> None:
        _register(self.orch, "claude_code")
        self.orch.create_task("Status test", "backend", ["done"], owner="claude_code")
        self.orch.claim_next_task("claude_code")

        tasks = self.orch.list_tasks()
        agents = self.orch.list_agents(active_only=True)
        roles = self.orch.get_roles()
        by_status: dict = {}
        for t in tasks:
            by_status[t["status"]] = by_status.get(t["status"], 0) + 1

        from datetime import datetime, timezone
        from orchestrator_mcp_server import _aggregate_team_lanes

        in_prog = [t for t in tasks if t.get("status") == "in_progress"]
        wp = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "pending"]
        wr = [t for t in tasks if isinstance(t.get("review_gate"), dict) and t["review_gate"].get("status") == "rejected"]

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "manager": roles.get("leader"), "roles": roles,
            "task_count": len(tasks), "task_status_counts": by_status,
            "team_lane_counters": _aggregate_team_lanes(tasks),
            "bug_count": len(self.orch.list_bugs()),
            "in_progress": [{"id": t.get("id"), "owner": t.get("owner"), "title": t.get("title"), "updated_at": t.get("updated_at")} for t in in_prog[:8]],
            "wingman_count": len(wp) + len(wr),
            "recovery_actions": [],
            "active_agents": [a["agent"] for a in agents],
            "active_agent_identities": [{"agent": a.get("agent"), "instance_id": a.get("instance_id"), "status": a.get("status"), "last_seen": a.get("last_seen")} for a in agents],
            "metrics": {"throughput": {"tasks_total": len(tasks)}},
        }
        missing = CANONICAL_STATUS_FIELDS - set(payload.keys())
        self.assertEqual(set(), missing)

    # ── superseded / archived statuses ────────────────────────────────

    def test_manager_can_set_superseded(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("old task", "backend", ["test"], owner="claude_code")
        result = self.orch.set_task_status(task["id"], "superseded", source="codex", note="replaced")
        self.assertEqual(result["status"], "superseded")
        self.assertIn("superseded_at", result)

    def test_team_member_cannot_set_superseded(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("old task", "backend", ["test"], owner="claude_code")
        with self.assertRaises(ValueError):
            self.orch.set_task_status(task["id"], "superseded", source="claude_code")

    def test_manager_can_set_archived(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("deferred", "backend", ["test"], owner="claude_code")
        result = self.orch.set_task_status(task["id"], "archived", source="codex", note="out of scope")
        self.assertEqual(result["status"], "archived")
        self.assertIn("archived_at", result)

    def test_team_member_cannot_set_archived(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("deferred", "backend", ["test"], owner="claude_code")
        with self.assertRaises(ValueError):
            self.orch.set_task_status(task["id"], "archived", source="claude_code")

    def test_superseded_not_claimable(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("old", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(task["id"], "superseded", source="codex")
        self.assertIsNone(self.orch.claim_next_task("claude_code"))

    def test_archived_not_claimable(self) -> None:
        _register(self.orch, "claude_code")
        task = self.orch.create_task("deferred", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(task["id"], "archived", source="codex")
        self.assertIsNone(self.orch.claim_next_task("claude_code"))

    def test_superseded_excluded_from_dedupe(self) -> None:
        _register(self.orch, "claude_code")
        t1 = self.orch.create_task("feature X", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        t2 = self.orch.create_task("feature X", "backend", ["test"], owner="claude_code")
        self.assertNotEqual(t1["id"], t2["id"])

    def test_archived_excluded_from_dedupe(self) -> None:
        _register(self.orch, "claude_code")
        t1 = self.orch.create_task("feature Y", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(t1["id"], "archived", source="codex")
        t2 = self.orch.create_task("feature Y", "backend", ["test"], owner="claude_code")
        self.assertNotEqual(t1["id"], t2["id"])

    def test_task_counts_include_new_statuses(self) -> None:
        _register(self.orch, "claude_code")
        t1 = self.orch.create_task("t1", "backend", ["test"], owner="claude_code")
        t2 = self.orch.create_task("t2", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        self.orch.set_task_status(t2["id"], "archived", source="codex")
        agents = self.orch.list_agents(active_only=False)
        cc = next(a for a in agents if a.get("agent") == "claude_code")
        self.assertEqual(cc["task_counts"]["superseded"], 1)
        self.assertEqual(cc["task_counts"]["archived"], 1)

    def test_reassign_stale_ignores_superseded_and_archived(self) -> None:
        _register(self.orch, "claude_code")
        t1 = self.orch.create_task("s1", "backend", ["test"], owner="claude_code")
        t2 = self.orch.create_task("a1", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        self.orch.set_task_status(t2["id"], "archived", source="codex")
        requeued = self.orch.requeue_stale_in_progress_tasks(stale_after_seconds=0)
        self.assertEqual(len(requeued), 0)

    def test_list_tasks_includes_all_statuses(self) -> None:
        _register(self.orch, "claude_code")
        t1 = self.orch.create_task("s1", "backend", ["test"], owner="claude_code")
        t2 = self.orch.create_task("a1", "backend", ["test"], owner="claude_code")
        self.orch.set_task_status(t1["id"], "superseded", source="codex")
        self.orch.set_task_status(t2["id"], "archived", source="codex")
        statuses = {t["status"] for t in self.orch.list_tasks()}
        self.assertIn("superseded", statuses)
        self.assertIn("archived", statuses)


# ── Agent identity tests ─────────────────────────────────────────────

class AgentIdentityTests(_OrchestratorTestCase):
    """Registration, list_agents, list_agent_instances, identity fields."""

    # ── registration ──────────────────────────────────────────────────

    def test_no_agents_returns_empty(self) -> None:
        self.assertEqual(self.orch.list_agents(active_only=True), [])

    def test_register_without_metadata_succeeds(self) -> None:
        entry = self.orch.register_agent("claude_code")
        self.assertEqual(entry["agent"], "claude_code")
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["metadata"]["instance_id"], "claude_code#default")

    def test_single_agent_identity_fields(self) -> None:
        _register(self.orch, "claude_code", instance_id="claude_code#w1")
        agents = self.orch.list_agents(active_only=True)
        self.assertEqual(len(agents), 1)
        a = agents[0]
        self.assertEqual(a["agent"], "claude_code")
        self.assertEqual(a["instance_id"], "claude_code#w1")
        self.assertEqual(a["status"], "active")
        self.assertIsNotNone(a["last_seen"])

    def test_multiple_agents_have_distinct_instance_ids(self) -> None:
        _register(self.orch, "claude_code", instance_id="cc1")
        _register(self.orch, "gemini", instance_id="gm1")
        _register(self.orch, "codex", instance_id="cx1")
        agents = self.orch.list_agents(active_only=True)
        ids = {a["instance_id"] for a in agents}
        self.assertEqual(ids, {"cc1", "gm1", "cx1"})

    def test_active_only_excludes_stale(self) -> None:
        _register(self.orch, "gemini", instance_id="gemini#stale")
        _make_stale(self.orch, "gemini")
        self.assertEqual(len(self.orch.list_agents(active_only=True)), 0)
        self.assertTrue(any(a["agent"] == "gemini" for a in self.orch.list_agents(active_only=False)))

    def test_offline_agent_preserves_metadata(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "i-42", "client": "cli", "model": "opus"})
        _make_stale(self.orch, "claude_code")
        agents = self.orch.list_agents(active_only=False)
        cc = next(a for a in agents if a["agent"] == "claude_code")
        self.assertEqual(cc["status"], "offline")
        self.assertEqual(cc["metadata"]["instance_id"], "i-42")
        self.assertEqual(cc["metadata"]["client"], "cli")

    def test_old_and_new_client_coexist(self) -> None:
        self.orch.register_agent("claude_code")  # old client, no instance_id
        self.orch.register_agent("gemini", metadata={"instance_id": "gem-v2"})
        agents = self.orch.list_agents(active_only=False)
        by_name = {a["agent"]: a for a in agents}
        self.assertEqual(by_name["claude_code"]["metadata"]["instance_id"], "claude_code#default")
        self.assertEqual(by_name["gemini"]["metadata"]["instance_id"], "gem-v2")

    def test_old_client_can_upgrade_instance_id(self) -> None:
        self.orch.register_agent("claude_code")
        self.assertEqual(self.orch.heartbeat("claude_code")["metadata"]["instance_id"], "claude_code#default")
        entry = self.orch.heartbeat("claude_code", metadata={"instance_id": "new-inst"})
        self.assertEqual(entry["metadata"]["instance_id"], "new-inst")

    # ── list_agent_instances ──────────────────────────────────────────

    def test_instances_empty(self) -> None:
        self.assertEqual(self.orch.list_agent_instances(), [])

    def test_instances_sorted_by_name_then_id(self) -> None:
        self.orch.register_agent("gemini", metadata={"instance_id": "g-2"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-2"})
        self.orch.register_agent("gemini", metadata={"instance_id": "g-1"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "cc-1"})
        pairs = [(i["agent_name"], i["instance_id"]) for i in self.orch.list_agent_instances()]
        self.assertEqual(pairs, sorted(pairs))

    def test_instances_default_id_sorted(self) -> None:
        self.orch.register_agent("gemini")
        self.orch.register_agent("claude_code")
        names = [i["agent_name"] for i in self.orch.list_agent_instances()]
        self.assertEqual(names, ["claude_code", "gemini"])

    def test_instances_have_project_root(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-1"})
        instances = self.orch.list_agent_instances()
        self.assertIn("project_root", instances[0])

    def test_instances_different_cwds(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-a", "cwd": "/proj/a"})
        self.orch.register_agent("claude_code", metadata={"instance_id": "c-b", "cwd": "/proj/b"})
        instances = self.orch.list_agent_instances()
        cc = [i for i in instances if i["agent_name"] == "claude_code"]
        self.assertEqual(len(cc), 2)
        self.assertEqual({i["instance_id"] for i in cc}, {"c-a", "c-b"})

    def test_stable_payload_keys_for_old_client(self) -> None:
        self.orch.register_agent("claude_code")
        agents = self.orch.list_agents(active_only=False)
        for key in ("agent", "status", "metadata", "last_seen"):
            self.assertIn(key, agents[0])
        self.assertIn("instance_id", agents[0]["metadata"])


# ── Metadata tests ───────────────────────────────────────────────────

class MetadataTests(_OrchestratorTestCase):
    """Metadata normalization, instance_id derivation, heartbeat merge."""

    # ── _normalize_agent_metadata priority ────────────────────────────

    def test_explicit_instance_id_preserved(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"instance_id": "my-id"})
        self.assertEqual(result["instance_id"], "my-id")

    def test_explicit_over_session_id(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"instance_id": "ex", "session_id": "s1"})
        self.assertEqual(result["instance_id"], "ex")

    def test_session_id_fallback(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"session_id": "sess-abc"})
        self.assertEqual(result["instance_id"], "sess-abc")

    def test_session_id_over_connection_id(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"session_id": "s", "connection_id": "c"})
        self.assertEqual(result["instance_id"], "s")

    def test_connection_id_fallback(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"connection_id": "conn-xyz"})
        self.assertEqual(result["instance_id"], "conn-xyz")

    def test_default_fallback_empty_metadata(self) -> None:
        self.assertEqual(self.orch._normalize_agent_metadata("claude_code", {})["instance_id"], "claude_code#default")

    def test_default_fallback_none_metadata(self) -> None:
        self.assertEqual(self.orch._normalize_agent_metadata("claude_code", None)["instance_id"], "claude_code#default")

    def test_default_fallback_empty_strings(self) -> None:
        result = self.orch._normalize_agent_metadata("gemini", {"instance_id": "", "session_id": "", "connection_id": ""})
        self.assertEqual(result["instance_id"], "gemini#default")

    def test_default_fallback_whitespace(self) -> None:
        result = self.orch._normalize_agent_metadata("codex", {"instance_id": "  ", "session_id": "  "})
        self.assertEqual(result["instance_id"], "codex#default")

    # ── merge behaviour ───────────────────────────────────────────────

    def test_merge_new_over_existing(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"model": "opus"}, existing={"model": "sonnet", "client": "vscode"})
        self.assertEqual(result["model"], "opus")
        self.assertEqual(result["client"], "vscode")

    def test_merge_none_metadata_uses_existing(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", None, existing={"instance_id": "from-existing"})
        self.assertEqual(result["instance_id"], "from-existing")

    def test_merge_new_instance_id_overrides_existing(self) -> None:
        result = self.orch._normalize_agent_metadata("claude_code", {"instance_id": "new"}, existing={"instance_id": "old"})
        self.assertEqual(result["instance_id"], "new")

    # ── _current_agent_instance_id_unlocked ───────────────────────────

    def test_current_id_unknown_agent(self) -> None:
        self.assertEqual(self.orch._current_agent_instance_id_unlocked("unknown"), "unknown#default")

    def test_current_id_with_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-99"})
        self.assertEqual(self.orch._current_agent_instance_id_unlocked("claude_code"), "inst-99")

    def test_current_id_with_session_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"session_id": "sess-42"})
        self.assertEqual(self.orch._current_agent_instance_id_unlocked("claude_code"), "sess-42")

    def test_current_id_no_metadata(self) -> None:
        self.orch.register_agent("claude_code")
        self.assertEqual(self.orch._current_agent_instance_id_unlocked("claude_code"), "claude_code#default")

    def test_current_id_agents_file_missing(self) -> None:
        self.orch.agents_path.unlink(missing_ok=True)
        self.assertEqual(self.orch._current_agent_instance_id_unlocked("claude_code"), "claude_code#default")

    # ── heartbeat merge ───────────────────────────────────────────────

    def test_heartbeat_preserves_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        entry = self.orch.heartbeat("claude_code")
        self.assertEqual(entry["metadata"]["instance_id"], "inst-42")

    def test_heartbeat_empty_metadata_preserves_instance_id(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "inst-42"})
        entry = self.orch.heartbeat("claude_code", metadata={})
        self.assertEqual(entry["metadata"]["instance_id"], "inst-42")

    def test_heartbeat_adds_field_without_losing_existing(self) -> None:
        self.orch.register_agent("claude_code", metadata={"client": "cli", "instance_id": "id-1"})
        entry = self.orch.heartbeat("claude_code", metadata={"model": "opus"})
        self.assertEqual(entry["metadata"]["client"], "cli")
        self.assertEqual(entry["metadata"]["model"], "opus")
        self.assertEqual(entry["metadata"]["instance_id"], "id-1")

    def test_heartbeat_new_instance_id_overrides(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "old-id"})
        entry = self.orch.heartbeat("claude_code", metadata={"instance_id": "new-id"})
        self.assertEqual(entry["metadata"]["instance_id"], "new-id")

    def test_heartbeat_updates_last_seen(self) -> None:
        self.orch.register_agent("claude_code", metadata={"instance_id": "id-1"})
        ts1 = self.orch.heartbeat("claude_code")["last_seen"]
        ts2 = self.orch.heartbeat("claude_code")["last_seen"]
        self.assertTrue(ts2 >= ts1)

    def test_heartbeat_unregistered_creates_entry(self) -> None:
        entry = self.orch.heartbeat("new_agent")
        self.assertEqual(entry["status"], "active")
        self.assertEqual(entry["metadata"]["instance_id"], "new_agent#default")

    def test_heartbeat_unregistered_with_instance_id(self) -> None:
        entry = self.orch.heartbeat("new_agent", metadata={"instance_id": "fresh-id"})
        self.assertEqual(entry["metadata"]["instance_id"], "fresh-id")


if __name__ == "__main__":
    unittest.main()
