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


def _team_metadata(root: Path, client: str, model: str, role: str, sid: str, cid: str) -> dict:
    return {
        "role": role,
        "client": client,
        "model": model,
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": sid,
        "connection_id": cid,
        "server_version": "0.1.0",
        "verification_source": "test",
    }


class TestDecisionsAndLearnings(unittest.TestCase):
    def test_orchestrator_record_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            decisions_file = root / "decisions" / "decisions.jsonl"
            self.assertFalse(decisions_file.exists())

            decision1 = orch.orchestrator_record_decision(
                topic="Database Choice",
                choice="PostgreSQL",
                rationale="Supports complex queries, ACID compliance.",
                agent="codex",
                references=["link1", "link2"],
            )
            self.assertTrue(decisions_file.exists())
            self.assertIn("DEC-", decision1["id"])

            decision2 = orch.orchestrator_record_decision(
                topic="Frontend Framework",
                choice="React",
                rationale="Large community, component-based.",
                agent="gemini",
            )

            with decisions_file.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(2, len(lines))

            loaded_decision1 = json.loads(lines[0])
            self.assertEqual(decision1["id"], loaded_decision1["id"])
            self.assertEqual("PostgreSQL", loaded_decision1["choice"])
            self.assertEqual("codex", loaded_decision1["agent"])
            self.assertEqual(["link1", "link2"], loaded_decision1["references"])

            loaded_decision2 = json.loads(lines[1])
            self.assertEqual(decision2["id"], loaded_decision2["id"])
            self.assertEqual("React", loaded_decision2["choice"])
            self.assertEqual("gemini", loaded_decision2["agent"])
            self.assertEqual([], loaded_decision2["references"]) # Default empty list

    def test_connect_to_leader_loads_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            decision1 = orch.orchestrator_record_decision(
                topic="Auth Strategy",
                choice="OAuth2",
                rationale="Standard, secure, widely adopted.",
                agent="claude_code",
                references=["rfc6749"],
            )
            decision2 = orch.orchestrator_record_decision(
                topic="CI/CD Tool",
                choice="GitHub Actions",
                rationale="Integrated with GitHub, flexible workflows.",
                agent="codex",
            )

            # Connect as an agent and verify decisions are loaded
            result = orch.connect_to_leader(
                agent="gemini",
                metadata=_team_metadata(root, "gemini-cli", "gemini", "team_member", "sid-g", "cid-g"),
                source="gemini",
            )

            self.assertTrue(result.get("connected"))
            identity = result.get("identity", {})
            self.assertIn("decisions", identity)
            loaded_decisions = identity["decisions"]

            self.assertEqual(2, len(loaded_decisions))
            self.assertEqual(decision1["id"], loaded_decisions[0]["id"])
            self.assertEqual("OAuth2", loaded_decisions[0]["choice"])
            self.assertEqual(decision2["id"], loaded_decisions[1]["id"])
            self.assertEqual("GitHub Actions", loaded_decisions[1]["choice"])

            # Verify that subsequent connections also load decisions
            result2 = orch.connect_to_leader(
                agent="claude_code",
                metadata=_team_metadata(root, "claude-cli", "claude", "team_member", "sid-c", "cid-c"),
                source="claude_code",
            )
            self.assertTrue(result2.get("connected"))
            self.assertIn("decisions", result2.get("identity", {}))
            self.assertEqual(2, len(result2["identity"]["decisions"]))

    def test_orchestrator_record_learning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            agent_name = "gemini"
            # Connect the agent to make it operational
            orch.connect_to_leader(
                agent=agent_name,
                metadata=_team_metadata(root, "gemini-cli", agent_name, "team_member", "sid-g", "cid-g"),
                source=agent_name,
            )
            history_path = root / "state" / "agents" / agent_name / "history.md"


            orch.orchestrator_record_learning(
                agent=agent_name,
                learning="Learned about persistent state management.",
                context="While implementing decision logging.",
            )
            self.assertTrue(history_path.exists())
            
            with history_path.open("r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("### Learning by gemini at", content)
            self.assertIn("**Learning:** Learned about persistent state management.", content)
            self.assertIn("**Context:** While implementing decision logging.", content)

            orch.orchestrator_record_learning(
                agent=agent_name,
                learning="Understood the importance of atomic writes.",
            )
            with history_path.open("r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("**Learning:** Understood the importance of atomic writes.", content)
            self.assertNotIn("**Context:**", content.split("---")[-1]) # No context for the second learning

    def test_connect_to_leader_loads_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = _make_policy(root / "policy.json")
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            agent_name = "claude_code"
            # Connect the agent to make it operational
            orch.connect_to_leader(
                agent=agent_name,
                metadata=_team_metadata(root, "claude-cli", agent_name, "team_member", "sid-cc", "cid-cc"),
                source=agent_name,
            )
            orch.orchestrator_record_learning(
                agent=agent_name,
                learning="Discovered a tricky test case.",
                context="When writing tests for new MCP tool.",
            )
            orch.orchestrator_record_learning(
                agent=agent_name,
                learning="Optimized a slow query.",
            )

            result = orch.connect_to_leader(
                agent=agent_name,
                metadata=_team_metadata(root, "claude-cli", agent_name, "team_member", "sid-cc", "cid-cc"),
                source=agent_name,
            )

            self.assertTrue(result.get("connected"))
            identity = result.get("identity", {})
            self.assertIn("history", identity)
            loaded_history = identity["history"]

            self.assertIn("### Learning by claude_code at", loaded_history)
            self.assertIn("**Learning:** Discovered a tricky test case.", loaded_history)
            self.assertIn("**Context:** When writing tests for new MCP tool.", loaded_history)
            self.assertIn("**Learning:** Optimized a slow query.", loaded_history)
