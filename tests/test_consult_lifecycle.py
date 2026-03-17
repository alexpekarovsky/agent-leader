"""Tests for consult-only team review workflow.

Validates the full consult lifecycle: create, respond, list, auto-close.
Ensures no task/execution side effects occur during consult operations.
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


class CreateConsultTests(unittest.TestCase):
    """Tests for create_consult."""

    def test_create_returns_consult_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="design",
                question="Should we use REST or gRPC for the new API?",
                context="Performance is critical for this endpoint.",
                target_agents=["claude_code", "gemini"],
            )

            self.assertTrue(consult["id"].startswith("CONSULT-"))
            self.assertEqual("codex", consult["source"])
            self.assertEqual("design", consult["consult_type"])
            self.assertEqual("Should we use REST or gRPC for the new API?", consult["question"])
            self.assertEqual("Performance is critical for this endpoint.", consult["context"])
            self.assertEqual(["claude_code", "gemini"], consult["target_agents"])
            self.assertEqual([], consult["responses"])
            self.assertEqual("open", consult["status"])
            self.assertIsNotNone(consult["created_at"])

    def test_create_with_no_target_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="general",
                question="Any thoughts on code style?",
            )

            self.assertEqual([], consult["target_agents"])
            self.assertEqual("open", consult["status"])

    def test_create_invalid_type_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.create_consult(
                    source="codex",
                    consult_type="invalid_type",
                    question="Bad type",
                )
            self.assertIn("Invalid consult_type", str(ctx.exception))

    def test_create_does_not_create_tasks(self) -> None:
        """Consult creation must NOT create any tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            tasks_before = orch.list_tasks()
            orch.create_consult(
                source="codex",
                consult_type="bug",
                question="Is this a real bug or expected?",
                target_agents=["claude_code"],
            )
            tasks_after = orch.list_tasks()

            self.assertEqual(len(tasks_before), len(tasks_after))

    def test_create_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="architecture",
                question="Monolith or microservices?",
            )

            raw_lines = orch.bus.events_path.read_text(encoding="utf-8").strip().split("\n")
            events = [json.loads(line) for line in raw_lines if line.strip()]
            consult_events = [e for e in events if e["type"] == "consult.created"]
            self.assertEqual(1, len(consult_events))
            self.assertEqual(consult["id"], consult_events[0]["payload"]["consult_id"])


class RespondConsultTests(unittest.TestCase):
    """Tests for respond_consult."""

    def test_respond_adds_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="design",
                question="REST or gRPC?",
                target_agents=["claude_code"],
            )

            updated = orch.respond_consult(
                consult_id=consult["id"],
                agent="claude_code",
                body="gRPC would be better for this use case due to streaming support.",
            )

            self.assertEqual(1, len(updated["responses"]))
            self.assertEqual("claude_code", updated["responses"][0]["agent"])
            self.assertIn("gRPC", updated["responses"][0]["body"])
            self.assertIsNotNone(updated["responses"][0]["responded_at"])

    def test_respond_nonexistent_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            with self.assertRaises(ValueError) as ctx:
                orch.respond_consult(
                    consult_id="CONSULT-nonexistent",
                    agent="claude_code",
                    body="Response",
                )
            self.assertIn("not found", str(ctx.exception))

    def test_respond_to_closed_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="design",
                question="REST or gRPC?",
                target_agents=["claude_code"],
            )
            # Respond to auto-close
            orch.respond_consult(consult["id"], "claude_code", "gRPC")

            with self.assertRaises(ValueError) as ctx:
                orch.respond_consult(consult["id"], "gemini", "REST")
            self.assertIn("already closed", str(ctx.exception))

    def test_respond_auto_closes_when_all_targets_respond(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="bug",
                question="Is this a real bug?",
                target_agents=["claude_code", "gemini"],
            )

            # First response - should stay open
            updated = orch.respond_consult(consult["id"], "claude_code", "Yes, looks like a bug")
            self.assertEqual("open", updated["status"])

            # Second response - should auto-close
            updated = orch.respond_consult(consult["id"], "gemini", "Agree, it's a bug")
            self.assertEqual("closed", updated["status"])
            self.assertIsNotNone(updated.get("closed_at"))

    def test_respond_no_targets_stays_open(self) -> None:
        """Consult with no target_agents stays open after any response."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="general",
                question="Open question",
            )

            updated = orch.respond_consult(consult["id"], "claude_code", "My thoughts...")
            self.assertEqual("open", updated["status"])

    def test_respond_does_not_create_tasks(self) -> None:
        """Responding to a consult must NOT create any tasks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="design",
                question="Any ideas?",
                target_agents=["claude_code"],
            )

            tasks_before = orch.list_tasks()
            orch.respond_consult(consult["id"], "claude_code", "Here's my review")
            tasks_after = orch.list_tasks()

            self.assertEqual(len(tasks_before), len(tasks_after))

    def test_respond_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="design",
                question="Review this",
                target_agents=["claude_code"],
            )
            orch.respond_consult(consult["id"], "claude_code", "LGTM")

            raw_lines = orch.bus.events_path.read_text(encoding="utf-8").strip().split("\n")
            events = [json.loads(line) for line in raw_lines if line.strip()]
            respond_events = [e for e in events if e["type"] == "consult.responded"]
            self.assertEqual(1, len(respond_events))
            self.assertEqual(consult["id"], respond_events[0]["payload"]["consult_id"])
            self.assertEqual("claude_code", respond_events[0]["payload"]["agent"])


class ListConsultsTests(unittest.TestCase):
    """Tests for list_consults."""

    def test_empty_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertEqual([], orch.list_consults())

    def test_list_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.create_consult(source="codex", consult_type="design", question="Q1")
            orch.create_consult(source="codex", consult_type="bug", question="Q2")

            self.assertEqual(2, len(orch.list_consults()))

    def test_filter_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            c1 = orch.create_consult(
                source="codex", consult_type="design", question="Q1",
                target_agents=["claude_code"],
            )
            orch.create_consult(source="codex", consult_type="bug", question="Q2")
            # Close c1 by responding
            orch.respond_consult(c1["id"], "claude_code", "Done")

            open_consults = orch.list_consults(status="open")
            closed_consults = orch.list_consults(status="closed")
            self.assertEqual(1, len(open_consults))
            self.assertEqual(1, len(closed_consults))

    def test_filter_by_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.create_consult(source="codex", consult_type="design", question="Q1")
            orch.create_consult(source="codex", consult_type="bug", question="Q2")
            orch.create_consult(source="codex", consult_type="design", question="Q3")

            design_consults = orch.list_consults(consult_type="design")
            self.assertEqual(2, len(design_consults))

    def test_filter_by_agent_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.create_consult(source="codex", consult_type="design", question="Q1")
            orch.create_consult(source="claude_code", consult_type="bug", question="Q2")

            codex_consults = orch.list_consults(agent="codex")
            self.assertEqual(1, len(codex_consults))

    def test_filter_by_agent_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.create_consult(
                source="codex", consult_type="design", question="Q1",
                target_agents=["claude_code"],
            )
            orch.create_consult(
                source="codex", consult_type="bug", question="Q2",
                target_agents=["gemini"],
            )

            cc_consults = orch.list_consults(agent="claude_code")
            self.assertEqual(1, len(cc_consults))
            self.assertEqual("Q1", cc_consults[0]["question"])


class ConsultNoSideEffectsTests(unittest.TestCase):
    """Ensure consult operations have zero task/execution side effects."""

    def test_no_claim_or_lease_created(self) -> None:
        """Consult lifecycle must not create any leases or claims."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            consult = orch.create_consult(
                source="codex",
                consult_type="architecture",
                question="Monolith or microservices?",
                target_agents=["claude_code", "gemini"],
            )
            orch.respond_consult(consult["id"], "claude_code", "Microservices")
            orch.respond_consult(consult["id"], "gemini", "Monolith")

            # No tasks should exist
            self.assertEqual(0, len(orch.list_tasks()))
            # No blockers should exist
            self.assertEqual(0, len(orch.list_blockers()))

    def test_consult_persists_to_state(self) -> None:
        """Consults should be persisted in consults.json."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            orch.create_consult(
                source="codex",
                consult_type="design",
                question="Review this design",
            )

            # Verify persistence
            state = json.loads((root / "state" / "consults.json").read_text(encoding="utf-8"))
            self.assertEqual(1, len(state))
            self.assertTrue(state[0]["id"].startswith("CONSULT-"))


class ConsultFullLifecycleTests(unittest.TestCase):
    """End-to-end consult lifecycle tests."""

    def test_full_lifecycle_create_respond_close(self) -> None:
        """Full lifecycle: create -> list open -> respond all -> list closed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            # Create
            consult = orch.create_consult(
                source="codex",
                consult_type="architecture",
                question="Should we add caching?",
                target_agents=["claude_code", "gemini"],
            )
            cid = consult["id"]

            # List open
            open_consults = orch.list_consults(status="open")
            self.assertEqual(1, len(open_consults))
            self.assertEqual(cid, open_consults[0]["id"])

            # First response
            orch.respond_consult(cid, "claude_code", "Yes, add Redis caching")
            open_consults = orch.list_consults(status="open")
            self.assertEqual(1, len(open_consults))

            # Second response - auto-closes
            orch.respond_consult(cid, "gemini", "Agree, caching would help")
            open_consults = orch.list_consults(status="open")
            closed_consults = orch.list_consults(status="closed")
            self.assertEqual(0, len(open_consults))
            self.assertEqual(1, len(closed_consults))
            self.assertEqual(2, len(closed_consults[0]["responses"]))

    def test_multiple_independent_consults(self) -> None:
        """Multiple consults operate independently."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)

            c1 = orch.create_consult(
                source="codex", consult_type="design", question="Q1",
                target_agents=["claude_code"],
            )
            c2 = orch.create_consult(
                source="codex", consult_type="bug", question="Q2",
                target_agents=["gemini"],
            )

            # Close only c1
            orch.respond_consult(c1["id"], "claude_code", "Response to Q1")

            open_consults = orch.list_consults(status="open")
            closed_consults = orch.list_consults(status="closed")
            self.assertEqual(1, len(open_consults))
            self.assertEqual(c2["id"], open_consults[0]["id"])
            self.assertEqual(1, len(closed_consults))
            self.assertEqual(c1["id"], closed_consults[0]["id"])


if __name__ == "__main__":
    unittest.main()
