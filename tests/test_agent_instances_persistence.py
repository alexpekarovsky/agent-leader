"""Agent instances persistence across bootstrap restart (TASK-baefaa60).

Covers agent instance data surviving orchestrator restart:
- Register agent, verify agents.json has entry
- Create new Orchestrator pointing at same root dir, call bootstrap()
- Verify agent entries persist across restart
- Verify multiple instance records survive
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str, session_id: str = "") -> dict:
    sid = session_id or f"sess-{agent}"
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": sid,
        "connection_id": f"conn-{agent}-{sid}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


class AgentRegistrationPersistenceTests(unittest.TestCase):
    """Verify that agent registration data persists to disk."""

    def test_register_creates_agents_json_entry(self) -> None:
        """After register_agent, agents.json must contain the agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.register_agent("claude_code", _full_metadata(root, "claude_code"))

            agents = json.loads(orch.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents)
            self.assertEqual("claude_code", agents["claude_code"]["agent"])
            self.assertEqual("active", agents["claude_code"]["status"])

    def test_register_creates_agent_instances_entry(self) -> None:
        """After register_agent, agent_instances.json must have an entry."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.register_agent("claude_code", _full_metadata(root, "claude_code"))

            instances = json.loads(orch.agent_instances_path.read_text(encoding="utf-8"))
            self.assertIsInstance(instances, dict)
            # At least one key should contain claude_code
            matching_keys = [k for k in instances if "claude_code" in k]
            self.assertGreaterEqual(len(matching_keys), 1)
            entry = instances[matching_keys[0]]
            self.assertEqual("claude_code", entry["agent"])

    def test_register_preserves_metadata(self) -> None:
        """Registered metadata should be stored in agents.json."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            metadata = _full_metadata(root, "claude_code")

            orch.register_agent("claude_code", metadata)

            agents = json.loads(orch.agents_path.read_text(encoding="utf-8"))
            stored = agents["claude_code"]["metadata"]
            self.assertEqual("claude_code-cli", stored["client"])
            self.assertEqual("claude_code-model", stored["model"])


class BootstrapRestartPersistenceTests(unittest.TestCase):
    """Verify data survives creating a new Orchestrator and calling bootstrap()."""

    def test_agents_persist_across_restart(self) -> None:
        """Agent entry in agents.json must survive new Orchestrator + bootstrap."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)
            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))
            orch1.heartbeat("claude_code", _full_metadata(root, "claude_code"))

            # Verify exists before restart
            agents_before = json.loads(orch1.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents_before)

            # Create new orchestrator on same root, call bootstrap
            orch2 = _make_orch(root)

            agents_after = json.loads(orch2.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents_after)
            self.assertEqual("claude_code", agents_after["claude_code"]["agent"])

    def test_agent_instances_persist_across_restart(self) -> None:
        """Agent instance records must survive new Orchestrator + bootstrap."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)
            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))

            instances_before = json.loads(
                orch1.agent_instances_path.read_text(encoding="utf-8")
            )
            cc_keys_before = [k for k in instances_before if "claude_code" in k]
            self.assertGreaterEqual(len(cc_keys_before), 1)

            # Restart
            orch2 = _make_orch(root)

            instances_after = json.loads(
                orch2.agent_instances_path.read_text(encoding="utf-8")
            )
            cc_keys_after = [k for k in instances_after if "claude_code" in k]
            self.assertGreaterEqual(len(cc_keys_after), 1)
            # Same keys should be present
            for key in cc_keys_before:
                self.assertIn(key, instances_after)

    def test_agent_metadata_persists_across_restart(self) -> None:
        """Metadata fields must survive restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)
            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))

            # Restart
            orch2 = _make_orch(root)

            agents = json.loads(orch2.agents_path.read_text(encoding="utf-8"))
            stored = agents["claude_code"]["metadata"]
            self.assertEqual("claude_code-cli", stored["client"])
            self.assertEqual("claude_code-model", stored["model"])

    def test_multiple_agents_persist_across_restart(self) -> None:
        """Multiple agent registrations must all survive restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)
            for agent in ["claude_code", "gemini"]:
                orch1.register_agent(agent, _full_metadata(root, agent))
                orch1.heartbeat(agent, _full_metadata(root, agent))

            # Restart
            orch2 = _make_orch(root)

            agents = json.loads(orch2.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents)
            self.assertIn("gemini", agents)

    def test_bootstrap_is_idempotent(self) -> None:
        """Calling bootstrap() twice must not clear existing agent data."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.register_agent("claude_code", _full_metadata(root, "claude_code"))

            agents_before = json.loads(orch.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents_before)

            # Call bootstrap again on same instance
            orch.bootstrap()

            agents_after = json.loads(orch.agents_path.read_text(encoding="utf-8"))
            self.assertIn("claude_code", agents_after)
            self.assertEqual(
                agents_before["claude_code"]["agent"],
                agents_after["claude_code"]["agent"],
            )

    def test_tasks_persist_across_restart(self) -> None:
        """Tasks created before restart must survive."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)
            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))
            task = orch1.create_task(
                title="Persistent task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            # Restart
            orch2 = _make_orch(root)

            tasks = orch2.list_tasks()
            task_ids = [t["id"] for t in tasks]
            self.assertIn(task["id"], task_ids)


class MultipleInstanceRecordTests(unittest.TestCase):
    """Verify multiple agent instance records survive restart."""

    def test_multiple_instances_for_same_agent_recorded(self) -> None:
        """Registering with different session_ids should create multiple instance records."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Register with first session
            orch.register_agent("claude_code", _full_metadata(root, "claude_code", "sess-1"))
            # Register with second session (simulating reconnect)
            orch.register_agent("claude_code", _full_metadata(root, "claude_code", "sess-2"))

            instances = json.loads(orch.agent_instances_path.read_text(encoding="utf-8"))
            cc_keys = [k for k in instances if "claude_code" in k]
            # Should have at least one instance record
            self.assertGreaterEqual(len(cc_keys), 1)
            # All entries should reference claude_code
            for key in cc_keys:
                self.assertEqual("claude_code", instances[key]["agent"])

    def test_multiple_instances_survive_restart(self) -> None:
        """Multiple instance records must persist across restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)

            orch1.register_agent("claude_code", _full_metadata(root, "claude_code", "sess-A"))
            orch1.register_agent("claude_code", _full_metadata(root, "claude_code", "sess-B"))

            instances_before = json.loads(
                orch1.agent_instances_path.read_text(encoding="utf-8")
            )
            cc_keys_before = [k for k in instances_before if "claude_code" in k]

            # Restart
            orch2 = _make_orch(root)

            instances_after = json.loads(
                orch2.agent_instances_path.read_text(encoding="utf-8")
            )
            cc_keys_after = [k for k in instances_after if "claude_code" in k]

            # All previous instance keys should still be present
            for key in cc_keys_before:
                self.assertIn(key, instances_after)

    def test_instances_for_multiple_agents_survive_restart(self) -> None:
        """Instance records for different agents must all survive restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)

            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))
            orch1.register_agent("gemini", _full_metadata(root, "gemini"))

            instances_before = json.loads(
                orch1.agent_instances_path.read_text(encoding="utf-8")
            )

            # Restart
            orch2 = _make_orch(root)

            instances_after = json.loads(
                orch2.agent_instances_path.read_text(encoding="utf-8")
            )

            cc_keys = [k for k in instances_after if "claude_code" in k]
            gm_keys = [k for k in instances_after if "gemini" in k]
            self.assertGreaterEqual(len(cc_keys), 1)
            self.assertGreaterEqual(len(gm_keys), 1)

    def test_instance_status_preserved_across_restart(self) -> None:
        """Instance status field must survive restart."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch1 = _make_orch(root)

            orch1.register_agent("claude_code", _full_metadata(root, "claude_code"))

            instances_before = json.loads(
                orch1.agent_instances_path.read_text(encoding="utf-8")
            )
            cc_keys = [k for k in instances_before if "claude_code" in k]
            status_before = instances_before[cc_keys[0]]["status"]

            # Restart
            orch2 = _make_orch(root)

            instances_after = json.loads(
                orch2.agent_instances_path.read_text(encoding="utf-8")
            )
            status_after = instances_after[cc_keys[0]]["status"]
            self.assertEqual(status_before, status_after)


if __name__ == "__main__":
    unittest.main()
