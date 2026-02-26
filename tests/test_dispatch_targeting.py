"""CORE-05 dispatch targeting semantics (agent-family vs instance-specific).

Tests publish_event audience filtering: agent-family targeting, wildcard,
broadcast, and mixed audience combinations.
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


def _register(orch: Orchestrator, agent: str, session_id: str = "sess-1") -> None:
    orch.register_agent(agent, metadata={
        "client": "test", "model": "test", "cwd": str(orch.root),
        "project_root": str(orch.root), "permissions_mode": "default",
        "sandbox_mode": "workspace-write", "session_id": session_id,
        "connection_id": f"conn-{agent}-{session_id}", "server_version": "0.1.0",
        "verification_source": "test",
    })


def _poll_events_for(orch: Orchestrator, agent: str) -> list:
    """Poll all events visible to an agent from cursor 0."""
    result = orch.poll_events(agent=agent, cursor=0, limit=200, auto_advance=False)
    return result["events"]


class DispatchTargetingTests(unittest.TestCase):
    """CORE-05: dispatch targeting semantics."""

    def _setup_agents(self, orch: Orchestrator) -> None:
        """Register claude_code (two sessions), gemini, and codex."""
        _register(orch, "claude_code", session_id="sess-1")
        _register(orch, "claude_code", session_id="sess-2")
        _register(orch, "gemini", session_id="sess-gm")
        _register(orch, "codex", session_id="sess-cx")

    def test_audience_agent_family_targets_agent(self) -> None:
        """publish_event with audience=['claude_code'] targets the agent family."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            # Clear events, publish targeted event
            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.targeted",
                source="codex",
                payload={"msg": "for claude_code"},
                audience=["claude_code"],
            )

            cc_events = _poll_events_for(orch, "claude_code")
            targeted = [e for e in cc_events if e.get("type") == "test.targeted"]
            self.assertGreaterEqual(len(targeted), 1)
            self.assertEqual("for claude_code", targeted[0]["payload"]["msg"])

    def test_both_instances_see_family_event(self) -> None:
        """Both instances of claude_code (sess-1, sess-2) see the family event.

        poll_events filters by agent name, not by instance, so both
        instances polling as 'claude_code' will see the same events.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.family",
                source="codex",
                payload={"msg": "family broadcast"},
                audience=["claude_code"],
            )

            # Both poll as the same agent name "claude_code"
            events_1 = orch.poll_events(agent="claude_code", cursor=0, limit=200, auto_advance=False)
            family_1 = [e for e in events_1["events"] if e.get("type") == "test.family"]
            self.assertGreaterEqual(len(family_1), 1)

            # A second poll at cursor 0 also sees it (same agent name)
            events_2 = orch.poll_events(agent="claude_code", cursor=0, limit=200, auto_advance=False)
            family_2 = [e for e in events_2["events"] if e.get("type") == "test.family"]
            self.assertGreaterEqual(len(family_2), 1)

    def test_audience_gemini_does_not_reach_claude_code(self) -> None:
        """publish_event with audience=['gemini'] does NOT reach claude_code."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.gemini_only",
                source="codex",
                payload={"msg": "gemini exclusive"},
                audience=["gemini"],
            )

            cc_events = _poll_events_for(orch, "claude_code")
            gemini_only = [e for e in cc_events if e.get("type") == "test.gemini_only"]
            self.assertEqual(0, len(gemini_only))

            # But gemini should see it
            gm_events = _poll_events_for(orch, "gemini")
            gemini_hits = [e for e in gm_events if e.get("type") == "test.gemini_only"]
            self.assertGreaterEqual(len(gemini_hits), 1)

    def test_wildcard_audience_reaches_all(self) -> None:
        """publish_event with audience=['*'] reaches all agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.wildcard",
                source="codex",
                payload={"msg": "for everyone"},
                audience=["*"],
            )

            for agent in ("claude_code", "gemini", "codex"):
                events = _poll_events_for(orch, agent)
                wildcard = [e for e in events if e.get("type") == "test.wildcard"]
                self.assertGreaterEqual(
                    len(wildcard), 1,
                    f"Agent {agent} should see wildcard event",
                )

    def test_no_audience_broadcast_reaches_all(self) -> None:
        """publish_event with no audience (broadcast) reaches all agents."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.broadcast",
                source="codex",
                payload={"msg": "broadcast message"},
            )

            for agent in ("claude_code", "gemini", "codex"):
                events = _poll_events_for(orch, agent)
                broadcasts = [e for e in events if e.get("type") == "test.broadcast"]
                self.assertGreaterEqual(
                    len(broadcasts), 1,
                    f"Agent {agent} should see broadcast event",
                )

    def test_mixed_agent_and_wildcard_audience(self) -> None:
        """Mixing agent and wildcard in audience works (everyone sees it)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.mixed",
                source="codex",
                payload={"msg": "mixed audience"},
                audience=["claude_code", "*"],
            )

            for agent in ("claude_code", "gemini", "codex"):
                events = _poll_events_for(orch, agent)
                mixed = [e for e in events if e.get("type") == "test.mixed"]
                self.assertGreaterEqual(
                    len(mixed), 1,
                    f"Agent {agent} should see mixed audience event",
                )

    def test_multi_agent_audience_reaches_targeted_not_others(self) -> None:
        """audience=['claude_code', 'gemini'] reaches both but not codex."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.multi",
                source="codex",
                payload={"msg": "for cc and gm"},
                audience=["claude_code", "gemini"],
            )

            # claude_code sees it
            cc_events = _poll_events_for(orch, "claude_code")
            cc_multi = [e for e in cc_events if e.get("type") == "test.multi"]
            self.assertGreaterEqual(len(cc_multi), 1)

            # gemini sees it
            gm_events = _poll_events_for(orch, "gemini")
            gm_multi = [e for e in gm_events if e.get("type") == "test.multi"]
            self.assertGreaterEqual(len(gm_multi), 1)

            # codex does NOT see it
            cx_events = _poll_events_for(orch, "codex")
            cx_multi = [e for e in cx_events if e.get("type") == "test.multi"]
            self.assertEqual(0, len(cx_multi))

    def test_empty_audience_treated_as_broadcast(self) -> None:
        """Empty audience list is treated as no audience (broadcast)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self._setup_agents(orch)

            orch.bus.events_path.write_text("", encoding="utf-8")
            orch.publish_event(
                event_type="test.empty_audience",
                source="codex",
                payload={"msg": "empty audience"},
                audience=[],
            )

            for agent in ("claude_code", "gemini", "codex"):
                events = _poll_events_for(orch, agent)
                hits = [e for e in events if e.get("type") == "test.empty_audience"]
                self.assertGreaterEqual(
                    len(hits), 1,
                    f"Agent {agent} should see event with empty audience",
                )


if __name__ == "__main__":
    unittest.main()
