"""Anti-spam cooldown tests for claim_next_task (TASK-6ee74b8f).

Verifies that rapid repeated empty claims are throttled server-side,
the throttled response includes dynamic retry_hint with backoff,
successful claims clear cooldown, and normal claim flow is unaffected.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_policy(path: Path, cooldown: float = 5) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {
            "heartbeat_timeout_minutes": 10,
            "lease_ttl_seconds": 300,
            "claim_cooldown_seconds": cooldown,
        },
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, cooldown: float = 5) -> Orchestrator:
    policy = _make_policy(root / "policy.json", cooldown=cooldown)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_agent(orch: Orchestrator, root: Path, agent: str) -> None:
    meta = _full_metadata(root, agent)
    orch.register_agent(agent, meta)
    orch.heartbeat(agent, meta)


class ClaimCooldownThrottleTests(unittest.TestCase):
    """Rapid repeated empty claims must be throttled server-side."""

    def test_first_empty_claim_returns_none(self) -> None:
        """First empty claim should return None (not throttled)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            result = orch.claim_next_task("claude_code")
            self.assertIsNone(result)

    def test_rapid_second_empty_claim_is_throttled(self) -> None:
        """Second empty claim within cooldown returns throttled dict."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            first = orch.claim_next_task("claude_code")
            self.assertIsNone(first)

            second = orch.claim_next_task("claude_code")
            self.assertIsNotNone(second)
            self.assertIsInstance(second, dict)
            self.assertTrue(second.get("throttled"))

    def test_throttled_response_structure(self) -> None:
        """Throttled response must include backoff_seconds, cooldown_seconds, message."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, cooldown=5)
            _setup_agent(orch, root, "claude_code")

            orch.claim_next_task("claude_code")  # empty → sets cooldown
            throttled = orch.claim_next_task("claude_code")

            self.assertTrue(throttled["throttled"])
            self.assertIn("backoff_seconds", throttled)
            self.assertIn("cooldown_seconds", throttled)
            self.assertIn("message", throttled)
            self.assertGreater(throttled["backoff_seconds"], 0)
            self.assertEqual(throttled["cooldown_seconds"], 5)
            self.assertIn("cooldown", throttled["message"])

    def test_cooldown_expires_after_window(self) -> None:
        """After cooldown period expires, empty claim returns None again."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, cooldown=0.1)  # 100ms cooldown
            _setup_agent(orch, root, "claude_code")

            orch.claim_next_task("claude_code")  # empty → sets cooldown
            time.sleep(0.15)  # wait past cooldown window
            result = orch.claim_next_task("claude_code")
            self.assertIsNone(result)


class ClaimCooldownNormalFlowTests(unittest.TestCase):
    """Normal claim flow (task available) must be unaffected by cooldown."""

    def test_claim_succeeds_when_task_available(self) -> None:
        """Claim with available task returns the task normally."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Normal claim test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")

            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])
            self.assertNotIn("throttled", claimed)

    def test_successful_claim_clears_cooldown(self) -> None:
        """After a successful claim, subsequent empty claim is not throttled."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            # Trigger cooldown with an empty claim
            first = orch.claim_next_task("claude_code")
            self.assertIsNone(first)

            # Add a task — this modifies tasks.json, so mtime changes.
            # The cooldown is automatically bypassed because mtime differs.
            orch.create_task(
                title="Clear cooldown test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertNotIn("throttled", claimed)
            self.assertEqual("in_progress", claimed["status"])

            # Now, empty claim should NOT be throttled (cooldown cleared by success)
            empty = orch.claim_next_task("claude_code")
            self.assertIsNone(empty)

    def test_cooldown_per_agent_isolation(self) -> None:
        """Cooldown for one agent does not affect another agent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            _setup_agent(orch, root, "gemini")

            # Trigger cooldown for claude_code
            orch.claim_next_task("claude_code")
            throttled = orch.claim_next_task("claude_code")
            self.assertTrue(throttled.get("throttled"))

            # gemini should NOT be throttled
            result = orch.claim_next_task("gemini")
            self.assertIsNone(result)  # None, not throttled


class ClaimCooldownPolicyTests(unittest.TestCase):
    """Cooldown seconds must respect policy configuration."""

    def test_custom_cooldown_seconds(self) -> None:
        """Custom claim_cooldown_seconds is respected."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, cooldown=10)
            _setup_agent(orch, root, "claude_code")

            self.assertEqual(10, orch._claim_cooldown_seconds())

    def test_zero_cooldown_disables_throttle(self) -> None:
        """Setting claim_cooldown_seconds=0 disables anti-spam."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, cooldown=0)
            _setup_agent(orch, root, "claude_code")

            first = orch.claim_next_task("claude_code")
            self.assertIsNone(first)
            # Second empty claim should also return None, not throttled
            second = orch.claim_next_task("claude_code")
            self.assertIsNone(second)

    def test_default_cooldown_is_5(self) -> None:
        """When no policy value set, default cooldown is 5 seconds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create policy without claim_cooldown_seconds
            raw = {
                "name": "test-policy",
                "roles": {"manager": "codex"},
                "routing": {"default": "codex"},
                "decisions": {},
                "triggers": {"heartbeat_timeout_minutes": 10},
            }
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(raw), encoding="utf-8")
            policy = Policy.load(policy_path)
            orch = Orchestrator(root=root, policy=policy)
            orch.bootstrap()

            self.assertEqual(5.0, orch._claim_cooldown_seconds())


class ClaimCooldownNoRegressionTests(unittest.TestCase):
    """Existing claim behaviors must not regress."""

    def test_second_claim_returns_none_when_task_consumed(self) -> None:
        """After claiming the only task, second claim returns None (no throttle)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Regression test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            first = orch.claim_next_task("claude_code")
            self.assertIsNotNone(first)

            # Second claim: no task, but no prior empty claim → returns None
            second = orch.claim_next_task("claude_code")
            self.assertIsNone(second)

    def test_lease_fields_intact_after_cooldown_feature(self) -> None:
        """Claim still produces correct lease fields."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")
            orch.create_task(
                title="Lease intact test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )

            claimed = orch.claim_next_task("claude_code")
            self.assertIn("lease", claimed)
            lease = claimed["lease"]
            self.assertTrue(lease["lease_id"].startswith("LEASE-"))
            self.assertEqual("claude_code", lease["owner"])
            self.assertEqual(300, lease["ttl_seconds"])

    def test_override_claim_unaffected(self) -> None:
        """Manager override claims bypass cooldown (mtime change from create_task)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            _setup_agent(orch, root, "claude_code")

            # Trigger cooldown
            orch.claim_next_task("claude_code")

            # Create task and set override — this changes tasks.json mtime,
            # so cooldown is automatically bypassed.
            task = orch.create_task(
                title="Override test",
                workstream="backend",
                owner="claude_code",
                acceptance_criteria=["done"],
            )
            orch.set_claim_override("claude_code", task["id"], source="codex")

            claimed = orch.claim_next_task("claude_code")
            self.assertIsNotNone(claimed)
            self.assertEqual("in_progress", claimed["status"])
            self.assertNotIn("throttled", claimed)


if __name__ == "__main__":
    unittest.main()
