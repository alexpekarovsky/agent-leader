"""Consolidated tests for event bus, polling, compaction, and event-driven wakeup."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from orchestrator.bus import EventBus
from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = str(REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh")
COMMON_SH = str(REPO_ROOT / "scripts" / "autopilot" / "common.sh")


def _make_policy(path: Path, event_retention_limit: int = 500) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10, "event_retention_limit": event_retention_limit},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, *, retention: int = 500, bootstrap: bool = True) -> Orchestrator:
    policy = _make_policy(root / "policy.json", retention)
    orch = Orchestrator(root=root, policy=policy)
    if bootstrap:
        orch.bootstrap()
    return orch


def _register(orch: Orchestrator, agent: str) -> None:
    orch.register_agent(agent, metadata={
        "client": agent, "model": agent,
        "cwd": str(orch.root), "project_root": str(orch.root),
        "permissions_mode": "default", "sandbox_mode": "workspace-write",
        "session_id": f"{agent}-sid", "connection_id": f"{agent}-cid",
        "server_version": "1.0", "verification_source": agent,
    })


class _OrchestratorMixin:
    """Shared setUp/tearDown for tests needing an Orchestrator."""

    retention: int = 500

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root, retention=self.retention)
        _register(self.orch, "claude_code")
        _register(self.orch, "gemini")

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ── Event Bus: publish, ack, lifecycle ──────────────────────────────

class EventBusTests(_OrchestratorMixin, unittest.TestCase):

    def test_publish_returns_event_with_id(self) -> None:
        event = self.orch.publish_event("test.ping", source="codex", payload={"msg": "hello"})
        self.assertTrue(event["event_id"].startswith("EVT-"))
        self.assertEqual(event["type"], "test.ping")
        self.assertEqual(event["payload"]["msg"], "hello")

    def test_publish_with_audience(self) -> None:
        event = self.orch.publish_event("sync", source="codex", payload={}, audience=["claude_code"])
        self.assertEqual(event["payload"]["audience"], ["claude_code"])

    def test_publish_persists_to_bus(self) -> None:
        self.orch.publish_event("test.persist", source="codex", payload={"x": 1})
        events = list(self.orch.bus.iter_events())
        self.assertTrue(any(e["type"] == "test.persist" for e in events))

    def test_ack_returns_confirmation(self) -> None:
        event = self.orch.publish_event("test.ack", source="codex")
        result = self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        self.assertTrue(result["acked"])
        self.assertEqual(result["event_id"], event["event_id"])

    def test_ack_is_idempotent(self) -> None:
        event = self.orch.publish_event("test.idem", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        acks_data = json.loads(self.orch.acks_path.read_text(encoding="utf-8"))
        self.assertEqual(acks_data.get("claude_code", []).count(event["event_id"]), 1)

    def test_ack_emits_event_acked(self) -> None:
        event = self.orch.publish_event("test.ackemit", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        all_events = list(self.orch.bus.iter_events())
        ack_events = [e for e in all_events if e["type"] == "event.acked"]
        self.assertGreater(len(ack_events), 0)

    def test_ack_per_agent_isolation(self) -> None:
        event = self.orch.publish_event("test.iso", source="codex")
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        acks_data = json.loads(self.orch.acks_path.read_text(encoding="utf-8"))
        self.assertIn(event["event_id"], acks_data.get("claude_code", []))
        self.assertNotIn(event["event_id"], acks_data.get("gemini", []))

    def test_full_lifecycle_publish_poll_ack(self) -> None:
        event = self.orch.publish_event("lifecycle.test", source="codex", payload={"step": 1})
        result1 = self.orch.poll_events(agent="claude_code")
        self.assertIn(event["event_id"], [e["event_id"] for e in result1["events"]])
        self.orch.ack_event(agent="claude_code", event_id=event["event_id"])
        result2 = self.orch.poll_events(agent="claude_code")
        self.assertNotIn(event["event_id"], [e["event_id"] for e in result2["events"]])


# ── Event Compaction ────────────────────────────────────────────────

class EventCompactionTests(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bus = EventBus(self.root / "bus")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_compaction_below_limit(self) -> None:
        for i in range(5):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=10)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 5)

    def test_compaction_archives_oldest(self) -> None:
        for i in range(20):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=10)
        self.assertEqual(result["archived"], 10)
        remaining = list(self.bus.iter_events())
        self.assertEqual(len(remaining), 10)
        self.assertEqual([e["payload"]["n"] for e in remaining], list(range(10, 20)))

    def test_archive_file_created(self) -> None:
        for i in range(15):
            self.bus.emit("test.evt", {"n": i}, source="codex")
        result = self.bus.compact_events(retention_limit=5)
        self.assertTrue(Path(result["archive_path"]).exists())

    def test_compaction_on_empty_bus(self) -> None:
        result = self.bus.compact_events(retention_limit=100)
        self.assertEqual(result["archived"], 0)
        self.assertEqual(result["retained"], 0)


class OrchestratorCompactionTests(_OrchestratorMixin, unittest.TestCase):
    retention = 10

    def test_cursors_adjusted_after_compaction(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.bulk.{i}", source="codex")
        self.orch.poll_events(agent="claude_code")
        self.orch.poll_events(agent="gemini")
        cursor_before = self.orch.get_agent_cursor("claude_code")
        result = self.orch.compact_events()
        adj = result["offset_adjustment"]
        self.assertGreater(adj, 0)
        self.assertEqual(self.orch.get_agent_cursor("claude_code"), max(0, cursor_before - adj))

    def test_no_event_loss_for_lagging_agent(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.seq.{i}", source="codex")
        self.orch.poll_events(agent="claude_code")
        self.orch.compact_events()
        self.assertEqual(self.orch.get_agent_cursor("gemini"), 0)
        poll = self.orch.poll_events(agent="gemini")
        self.assertGreater(len(poll["events"]), 0)

    def test_compaction_emits_events_compacted_event(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.emit.{i}", source="codex")
        self.orch.compact_events()
        all_events = list(self.orch.bus.iter_events())
        compacted = [e for e in all_events if e["type"] == "events.compacted"]
        self.assertEqual(len(compacted), 1)
        self.assertIn("archived", compacted[0]["payload"])

    def test_poll_after_compaction_seamless(self) -> None:
        for i in range(15):
            self.orch.publish_event(f"test.pre.{i}", source="codex")
        self.orch.poll_events(agent="claude_code", limit=10)
        for i in range(5):
            self.orch.publish_event(f"test.post.{i}", source="codex")
        self.orch.compact_events()
        result = self.orch.poll_events(agent="claude_code")
        self.assertTrue(any(e["type"].startswith("test.post.") for e in result["events"]))

    def test_explicit_retention_overrides_policy(self) -> None:
        for i in range(20):
            self.orch.publish_event(f"test.override.{i}", source="codex")
        result = self.orch.compact_events(retention_limit=5)
        self.assertEqual(result["retained"], 5)


# ── Poll Events: result shape, cursor, audience, limit ─────────────

class PollEventsTests(_OrchestratorMixin, unittest.TestCase):

    def test_result_shape(self) -> None:
        result = self.orch.poll_events(agent="claude_code", timeout_ms=0)
        for key in ("agent", "cursor", "next_cursor", "events"):
            self.assertIn(key, result)
        self.assertEqual(result["agent"], "claude_code")

    def test_events_have_offset(self) -> None:
        self.orch.publish_event("test.ping", source="codex", payload={"msg": "hi"})
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        for event in result["events"]:
            self.assertIn("offset", event)
            self.assertIsInstance(event["offset"], int)

    def test_auto_advance_moves_cursor(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        for i in range(5):
            self.orch.bus.emit(f"test.e.{i}", {"n": i}, source="test")
        r1 = self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)
        self.assertEqual(len(r1["events"]), 5)
        r2 = self.orch.poll_events(agent="claude_code", auto_advance=True, timeout_ms=0)
        self.assertEqual(r2["events"], [])

    def test_auto_advance_false_keeps_cursor(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        for i in range(3):
            self.orch.bus.emit(f"test.e.{i}", {"n": i}, source="test")
        r1 = self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
        r2 = self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
        self.assertEqual(len(r1["events"]), len(r2["events"]))

    def test_explicit_cursor_overrides_stored(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        for i in range(10):
            self.orch.bus.emit(f"test.e.{i}", {"n": i}, source="test")
        self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)
        result = self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=False, timeout_ms=0)
        self.assertEqual(len(result["events"]), 10)

    def test_limit_caps_events(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        for i in range(20):
            self.orch.bus.emit(f"test.e.{i}", {"n": i}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, limit=5, timeout_ms=0)
        self.assertEqual(len(result["events"]), 5)

    def test_limit_pagination(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        for i in range(10):
            self.orch.bus.emit(f"test.e.{i}", {"n": i}, source="test")
        r1 = self.orch.poll_events(agent="claude_code", cursor=0, limit=3, auto_advance=True, timeout_ms=0)
        self.assertEqual(len(r1["events"]), 3)
        r2 = self.orch.poll_events(agent="claude_code", auto_advance=True, timeout_ms=0)
        self.assertEqual(len(r2["events"]), 7)

    def test_no_audience_visible_to_all(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        self.orch.bus.emit("broadcast", {"msg": "hello"}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        self.assertEqual(len(result["events"]), 1)

    def test_targeted_audience_visible_to_target(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        self.orch.bus.emit("targeted", {"audience": ["claude_code"]}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        self.assertEqual(len([e for e in result["events"] if e["type"] == "targeted"]), 1)

    def test_targeted_audience_hidden_from_others(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        self.orch.bus.emit("targeted", {"audience": ["gemini"]}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        self.assertEqual(len([e for e in result["events"] if e["type"] == "targeted"]), 0)

    def test_wildcard_audience_visible_to_all(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        self.orch.bus.emit("wild", {"audience": ["*"]}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        self.assertEqual(len([e for e in result["events"] if e["type"] == "wild"]), 1)

    def test_multi_audience_includes_member(self) -> None:
        self.orch.publish_event("multi", source="codex", payload={}, audience=["gemini", "claude_code"])
        result = self.orch.poll_events(agent="claude_code", cursor=0)
        self.assertTrue(any(e["type"] == "multi" for e in result["events"]))

    def test_filtered_events_still_advance_cursor(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        self.orch.bus.emit("e1", {"audience": ["gemini"]}, source="test")
        self.orch.bus.emit("e2", {"msg": "for all"}, source="test")
        self.orch.bus.emit("e3", {"audience": ["gemini"]}, source="test")
        result = self.orch.poll_events(agent="claude_code", cursor=0, auto_advance=True, timeout_ms=0)
        self.assertEqual(len([e for e in result["events"] if e["type"] == "e2"]), 1)
        self.assertEqual(result["next_cursor"], 3)

    def test_zero_timeout_returns_immediately(self) -> None:
        self.orch.bus.events_path.write_text("", encoding="utf-8")
        start = time.time()
        result = self.orch.poll_events(agent="claude_code", cursor=0, timeout_ms=0)
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(result["events"], [])

    def test_registration_events_visible(self) -> None:
        result = self.orch.poll_events(agent="claude_code")
        types = {e["type"] for e in result["events"]}
        self.assertIn("agent.registered", types)


# ── Event-Driven Wakeup ────────────────────────────────────────────

def _make_cli_stub(bin_dir: Path, name: str) -> None:
    stub = bin_dir / name
    stub.write_text(f"#!/usr/bin/env bash\ntouch '{bin_dir / f'.{name}_invoked'}'\necho 'stub invoked'\n")
    stub.chmod(0o755)


def _bootstrap_shell_root(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    policy = {
        "name": "codex-manager", "roles": {"manager": "codex"},
        "routing": {"default": "codex"}, "decisions": {},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }
    (root / "config" / "policy.codex-manager.json").write_text(json.dumps(policy), encoding="utf-8")
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    for name, payload in {
        "agents.json": {},
        "roles.json": {"leader": "codex", "leader_instance_id": "codex#default", "team_members": []},
        "blockers.json": [], "bugs.json": [],
    }.items():
        (state / name).write_text(json.dumps(payload), encoding="utf-8")
    (root / "bus").mkdir(parents=True, exist_ok=True)
    (state / "tasks.json").write_text("[]", encoding="utf-8")


class EventDrivenWakeupTests(unittest.TestCase):
    _TIMEOUT = 20

    def test_wait_for_signal_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", "-c", f'source "{COMMON_SH}" && wait_for_task_signal "{tmp}" testbot 2 1'],
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_wait_for_signal_detects_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            signal = Path(tmp) / "state" / ".wakeup-testbot"
            signal.parent.mkdir(parents=True, exist_ok=True)
            signal.write_text("baseline", encoding="utf-8")

            def _touch():
                time.sleep(1)
                signal.write_text("updated", encoding="utf-8")

            t = threading.Thread(target=_touch)
            t.start()
            result = subprocess.run(
                ["bash", "-c", f'source "{COMMON_SH}" && wait_for_task_signal "{tmp}" testbot 5 1'],
                capture_output=True, text=True, timeout=10,
            )
            t.join()
            self.assertEqual(result.returncode, 0)

    def test_event_driven_idle_no_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_shell_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                ["bash", WORKER_LOOP, "--cli", "codex", "--agent", "codex",
                 "--project-root", str(project), "--log-dir", str(log_dir),
                 "--max-idle-cycles", "2", "--event-driven",
                 "--event-max-wait", "2", "--event-poll-interval", "1"],
                capture_output=True, text=True, timeout=self._TIMEOUT, env=env,
            )
            self.assertFalse((bin_dir / ".codex_invoked").exists())
            self.assertIn("waiting for wakeup signal", result.stderr)

    def test_event_driven_wakeup_triggers_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_shell_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")

            signal_path = project / "state" / ".wakeup-codex"

            def _touch():
                time.sleep(2)
                signal_path.write_text("wakeup", encoding="utf-8")

            t = threading.Thread(target=_touch)
            t.start()

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                ["bash", WORKER_LOOP, "--cli", "codex", "--agent", "codex",
                 "--project-root", str(project), "--log-dir", str(log_dir),
                 "--max-idle-cycles", "2", "--event-driven",
                 "--event-max-wait", "5", "--event-poll-interval", "1"],
                capture_output=True, text=True, timeout=self._TIMEOUT, env=env,
            )
            t.join()
            self.assertIn("wakeup signal received", result.stderr)

    def test_fallback_polling_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            _bootstrap_shell_root(project)
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            _make_cli_stub(bin_dir, "codex")

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
            env["ORCHESTRATOR_ROOT"] = str(project)
            result = subprocess.run(
                ["bash", WORKER_LOOP, "--cli", "codex", "--agent", "codex",
                 "--project-root", str(project), "--log-dir", str(log_dir),
                 "--max-idle-cycles", "1", "--idle-backoff", "1"],
                capture_output=True, text=True, timeout=self._TIMEOUT, env=env,
            )
            self.assertNotIn("waiting for wakeup signal", result.stderr)

    def test_touch_wakeup_signals_on_task_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bus").mkdir()
            (root / "state").mkdir()
            policy = Policy(name="test", roles={}, routing={}, decisions={}, triggers={})
            orch = Orchestrator(root=root, policy=policy)
            tasks = [
                {"id": "T-1", "owner": "claude_code", "status": "assigned"},
                {"id": "T-2", "owner": "gemini", "status": "done"},
                {"id": "T-3", "owner": "codex", "status": "bug_open"},
            ]
            orch._write_json(orch.tasks_path, tasks)
            orch._touch_wakeup_signals()
            self.assertTrue((root / "state" / ".wakeup-claude_code").exists())
            self.assertTrue((root / "state" / ".wakeup-codex").exists())
            self.assertFalse((root / "state" / ".wakeup-gemini").exists())

    def test_supervisor_event_driven_flag(self) -> None:
        from orchestrator.supervisor import SupervisorConfig, proc_cmd
        cfg = SupervisorConfig(event_driven=True)
        cfg.finalise()
        for name in ("claude", "gemini", "codex_worker", "wingman"):
            self.assertIn("--event-driven", proc_cmd(name, cfg))
        self.assertNotIn("--event-driven", proc_cmd("manager", cfg))

    def test_supervisor_no_event_driven_by_default(self) -> None:
        from orchestrator.supervisor import SupervisorConfig, proc_cmd
        cfg = SupervisorConfig(event_driven=False)
        cfg.finalise()
        for name in ("claude", "gemini", "codex_worker", "wingman"):
            self.assertNotIn("--event-driven", proc_cmd(name, cfg))


class AgentCursorTests(unittest.TestCase):
    def test_unknown_agent_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            self.assertEqual(0, orch.get_agent_cursor("nonexistent"))

    def test_cursor_advances_after_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            _register(orch, "claude_code")
            orch.publish_event("test.ping", "orchestrator", {"v": 1})
            before = orch.get_agent_cursor("claude_code")
            orch.poll_events("claude_code", timeout_ms=0)
            self.assertGreater(orch.get_agent_cursor("claude_code"), before)

    def test_cursor_unchanged_without_auto_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            _register(orch, "claude_code")
            orch.publish_event("test.no", "orchestrator", {"v": 1})
            before = orch.get_agent_cursor("claude_code")
            orch.poll_events("claude_code", timeout_ms=0, auto_advance=False)
            self.assertEqual(before, orch.get_agent_cursor("claude_code"))

    def test_independent_cursors_per_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orch(Path(tmp))
            _register(orch, "claude_code")
            _register(orch, "gemini")
            orch.publish_event("test.multi", "orchestrator", {"v": 1})
            orch.poll_events("claude_code", timeout_ms=0)
            self.assertGreater(orch.get_agent_cursor("claude_code"),
                               orch.get_agent_cursor("gemini"))


if __name__ == "__main__":
    unittest.main()
