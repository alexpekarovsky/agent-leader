"""Tests for discover_agents and record_architecture_decision.

Validates agent discovery (registered + inferred) and architecture
decision recording with vote tallying and persistence.
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
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path) -> Orchestrator:
    policy = _make_policy(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _register_agent(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, {
        "client": "test-client",
        "model": "test-model",
        "cwd": str(orch.root),
        "project_root": str(orch.root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"cid-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    })


class DiscoverAgentsTests(unittest.TestCase):
    """Tests for discover_agents."""

    def test_no_agents_returns_empty(self) -> None:
        """discover_agents with no agents registered should return empty or inferred only."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.discover_agents()

            self.assertEqual(0, result["registered_count"])
            self.assertIsInstance(result["agents"], list)

    def test_registered_agent_appears(self) -> None:
        """A registered agent should appear in discover_agents output."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            result = orch.discover_agents()

            self.assertGreaterEqual(result["registered_count"], 1)
            agents = result["agents"]
            cc = [a for a in agents if a.get("agent") == "claude_code"]
            self.assertTrue(len(cc) >= 1)

    def test_inferred_agent_from_task_owner(self) -> None:
        """An agent referenced as task owner but not registered should be inferred."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            orch.create_task(
                title="Test task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            result = orch.discover_agents()

            agents = result["agents"]
            cc = [a for a in agents if a.get("agent") == "claude_code"]
            self.assertTrue(len(cc) >= 1)

    def test_inferred_agent_has_unknown_status(self) -> None:
        """An inferred-only agent should have status 'unknown' and inferred=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # Publish event from unregistered agent
            orch.publish_event("test.ping", "mystery_agent", {"hello": True})

            result = orch.discover_agents()

            inferred = [a for a in result["agents"] if a.get("agent") == "mystery_agent"]
            self.assertEqual(1, len(inferred))
            self.assertEqual("unknown", inferred[0]["status"])
            self.assertTrue(inferred[0]["inferred"])
            self.assertFalse(inferred[0]["verified"])

    def test_registered_not_duplicated_as_inferred(self) -> None:
        """A registered agent should not also appear as inferred."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            # Also create a task owned by claude_code (would infer it)
            orch.create_task(
                title="Task",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            result = orch.discover_agents()

            cc_entries = [a for a in result["agents"] if a.get("agent") == "claude_code"]
            self.assertEqual(1, len(cc_entries), "claude_code should appear exactly once")

    def test_active_only_filters(self) -> None:
        """discover_agents(active_only=True) should exclude stale registered agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")
            # Make agent stale
            agents = orch._read_json(orch.agents_path)
            agents["claude_code"]["last_seen"] = "2020-01-01T00:00:00+00:00"
            orch._write_json(orch.agents_path, agents)

            result = orch.discover_agents(active_only=True)

            self.assertEqual(0, result["registered_count"])

    def test_agents_sorted_by_name(self) -> None:
        """discover_agents output should be sorted by agent name."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "gemini")
            _register_agent(orch, "claude_code")
            _register_agent(orch, "codex")

            result = orch.discover_agents()

            names = [a["agent"] for a in result["agents"]]
            self.assertEqual(sorted(names), names)

    def test_result_structure(self) -> None:
        """discover_agents should return registered_count, inferred_only_count, agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            result = orch.discover_agents()

            self.assertIn("registered_count", result)
            self.assertIn("inferred_only_count", result)
            self.assertIn("agents", result)
            self.assertIsInstance(result["registered_count"], int)
            self.assertIsInstance(result["inferred_only_count"], int)
            self.assertIsInstance(result["agents"], list)


class RecordArchitectureDecisionTests(unittest.TestCase):
    """Tests for record_architecture_decision."""

    def test_records_decision_to_file(self) -> None:
        """record_architecture_decision should create an ADR markdown file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="API format",
                options=["REST", "GraphQL"],
                votes={"codex": "REST", "claude_code": "REST", "gemini": "GraphQL"},
                rationale={"codex": "Simpler", "claude_code": "More familiar", "gemini": "More flexible"},
            )

            self.assertTrue(path.exists())
            content = path.read_text(encoding="utf-8")
            self.assertIn("API format", content)
            self.assertIn("REST", content)
            self.assertIn("GraphQL", content)
            self.assertIn("Winner: REST", content)

    def test_decision_file_contains_votes(self) -> None:
        """ADR file should contain each member's vote."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="DB choice",
                options=["SQLite", "PostgreSQL"],
                votes={"codex": "SQLite", "claude_code": "SQLite", "gemini": "PostgreSQL"},
                rationale={"codex": "Simple", "claude_code": "Local", "gemini": "Scalable"},
            )

            content = path.read_text(encoding="utf-8")
            self.assertIn("codex: SQLite", content)
            self.assertIn("claude_code: SQLite", content)
            self.assertIn("gemini: PostgreSQL", content)

    def test_decision_file_contains_rationale(self) -> None:
        """ADR file should contain each member's rationale."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="Testing",
                options=["unittest", "pytest"],
                votes={"codex": "pytest", "claude_code": "unittest", "gemini": "pytest"},
                rationale={"codex": "Better fixtures", "claude_code": "Stdlib", "gemini": "Plugins"},
            )

            content = path.read_text(encoding="utf-8")
            self.assertIn("Better fixtures", content)
            self.assertIn("Stdlib", content)
            self.assertIn("Plugins", content)

    def test_missing_vote_raises_error(self) -> None:
        """Missing a vote from a required member should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.record_architecture_decision(
                    topic="Incomplete",
                    options=["A", "B"],
                    votes={"codex": "A", "claude_code": "A"},  # missing gemini
                    rationale={},
                )
            self.assertIn("gemini", str(ctx.exception))

    def test_unknown_option_in_vote_raises_error(self) -> None:
        """Voting for an option not in the list should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.record_architecture_decision(
                    topic="Bad vote",
                    options=["A", "B"],
                    votes={"codex": "A", "claude_code": "C", "gemini": "A"},
                    rationale={},
                )
            self.assertIn("unknown option", str(ctx.exception).lower())

    def test_winner_is_majority(self) -> None:
        """The winner should be the option with the most votes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="Majority test",
                options=["Alpha", "Beta"],
                votes={"codex": "Beta", "claude_code": "Beta", "gemini": "Alpha"},
                rationale={"codex": "r1", "claude_code": "r2", "gemini": "r3"},
            )

            content = path.read_text(encoding="utf-8")
            self.assertIn("Winner: Beta", content)

    def test_decision_id_format(self) -> None:
        """Decision file should be named ADR-{hex}.md."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="ID test",
                options=["X", "Y"],
                votes={"codex": "X", "claude_code": "X", "gemini": "Y"},
                rationale={},
            )

            self.assertTrue(path.name.startswith("ADR-"))
            self.assertTrue(path.name.endswith(".md"))

    def test_decision_emits_event(self) -> None:
        """record_architecture_decision should emit an architecture.decided event."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _register_agent(orch, "claude_code")

            orch.record_architecture_decision(
                topic="Event test",
                options=["A", "B"],
                votes={"codex": "A", "claude_code": "A", "gemini": "B"},
                rationale={},
            )

            # Check events for architecture.decided
            result = orch.poll_events("claude_code", timeout_ms=0)
            types = [e["type"] for e in result["events"]]
            self.assertIn("architecture.decided", types)

    def test_missing_rationale_uses_default(self) -> None:
        """Missing rationale for a member should use default text."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            path = orch.record_architecture_decision(
                topic="No rationale",
                options=["A", "B"],
                votes={"codex": "A", "claude_code": "A", "gemini": "B"},
                rationale={},  # Empty rationale
            )

            content = path.read_text(encoding="utf-8")
            self.assertIn("No rationale provided", content)


if __name__ == "__main__":
    unittest.main()
