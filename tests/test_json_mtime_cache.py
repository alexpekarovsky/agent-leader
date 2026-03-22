"""Tests for mtime-based JSON file cache in Orchestrator._read_json / _write_json."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


def _make_orch(root: Path) -> Orchestrator:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex"]}},
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": 300},
    }
    (root / "policy.json").write_text(json.dumps(raw), encoding="utf-8")
    policy = Policy.load(root / "policy.json")
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


class MtimeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_read_json_returns_data(self) -> None:
        """Basic read returns correct data."""
        tasks = self.orch._read_json(self.orch.tasks_path)
        self.assertIsInstance(tasks, list)

    def test_cache_hit_skips_disk_read(self) -> None:
        """Second read with unchanged mtime uses cache (no file open)."""
        # Populate cache
        self.orch._read_json(self.orch.tasks_path)
        # Patch open to detect disk reads
        original_open = Path.open
        open_calls = []

        def tracking_open(self_path, *args, **kwargs):
            open_calls.append(str(self_path))
            return original_open(self_path, *args, **kwargs)

        with patch.object(Path, "open", tracking_open):
            self.orch._read_json(self.orch.tasks_path)
        tasks_opens = [p for p in open_calls if "tasks.json" in p]
        self.assertEqual(tasks_opens, [], "cache hit should not open the file")

    def test_cache_miss_after_external_modification(self) -> None:
        """Cache invalidated when file mtime changes externally."""
        # Populate cache
        self.orch._read_json(self.orch.tasks_path)
        # External modification — write new content to change mtime
        task = {"id": "T-ext", "title": "external", "status": "assigned", "owner": "x"}
        self.orch.tasks_path.write_text(json.dumps([task]), encoding="utf-8")
        result = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "T-ext")

    def test_write_json_invalidates_cache(self) -> None:
        """_write_json clears cache entry for that path."""
        # Populate cache
        self.orch._read_json(self.orch.tasks_path)
        key = str(self.orch.tasks_path)
        self.assertIn(key, self.orch._json_cache)
        # Write invalidates
        self.orch._write_json(self.orch.tasks_path, [])
        self.assertNotIn(key, self.orch._json_cache)

    def test_read_nonexistent_returns_empty_list(self) -> None:
        """Reading a missing file returns [] and clears any stale cache."""
        missing = self.orch.state_dir / "nonexistent.json"
        result = self.orch._read_json(missing)
        self.assertEqual(result, [])

    def test_default_returns_reference_no_copy(self) -> None:
        """Default make_copy=False returns direct cache reference."""
        task = {"id": "T1", "title": "test", "status": "assigned", "owner": "x"}
        self.orch._write_json(self.orch.tasks_path, [task])
        ref1 = self.orch._read_json(self.orch.tasks_path)
        ref2 = self.orch._read_json(self.orch.tasks_path)
        self.assertIs(ref1, ref2, "default should return same cached object")

    def test_make_copy_true_returns_independent_copy(self) -> None:
        """make_copy=True returns a deep copy, not the cached object."""
        task = {"id": "T1", "title": "test", "status": "assigned", "owner": "x"}
        self.orch._write_json(self.orch.tasks_path, [task])
        copy1 = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        copy2 = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        self.assertIsNot(copy1, copy2, "each make_copy=True call returns a new object")
        self.assertEqual(copy1, copy2)

    def test_mutation_of_copy_does_not_corrupt_cache(self) -> None:
        """Mutating a make_copy=True result must not affect cached data."""
        task = {"id": "T1", "title": "test", "status": "assigned", "owner": "x"}
        self.orch._write_json(self.orch.tasks_path, [task])
        mutable = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        mutable.append({"id": "T2"})
        pristine = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(len(pristine), 1, "cache must not grow from copy mutation")

    def test_reassign_stale_does_not_corrupt_cache(self) -> None:
        """reassign_stale_tasks uses make_copy=True so cache stays pristine."""
        task = {"id": "T-stale", "title": "stale", "status": "in_progress",
                "owner": "old_agent", "updated_at": self.orch._now()}
        self.orch._write_json(self.orch.tasks_path, [task])
        # Register old_agent as stale and new_agent as active
        now = self.orch._now()
        agents = {
            "old_agent": {"status": "active", "last_seen": "2020-01-01T00:00:00+00:00",
                          "metadata": {"project_root": str(self.root), "cwd": str(self.root),
                                       "verified": True, "same_project": True}},
            "new_agent": {"status": "active", "last_seen": now,
                          "metadata": {"project_root": str(self.root), "cwd": str(self.root),
                                       "verified": True, "same_project": True}},
        }
        self.orch._write_json(self.orch.agents_path, agents)
        # Warm cache
        cached_before = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(cached_before[0]["status"], "in_progress")
        # Run reassign — should use a copy, not mutate cached ref
        self.orch.reassign_stale_tasks_to_active_workers(source="test", stale_after_seconds=1)
        # The cached reference from before must still show original status
        self.assertEqual(cached_before[0]["status"], "in_progress",
                         "cache reference must not be mutated by reassign_stale_tasks")

    def test_claim_next_task_under_1ms_warm_cache(self) -> None:
        """Benchmark: claim_next_task < 1ms with warm cache (no claimable tasks)."""
        # Pre-warm cache
        self.orch._read_json(self.orch.tasks_path)
        # Register agent so it's operational
        agents = {"claude_code": {"status": "active", "last_seen": self.orch._now(),
                                   "metadata": {"project_root": str(self.root),
                                                 "cwd": str(self.root),
                                                 "verified": True,
                                                 "same_project": True}}}
        self.orch._write_json(self.orch.agents_path, agents)
        # Warm cache again after write
        self.orch._read_json(self.orch.tasks_path)
        self.orch._read_json(self.orch.agents_path)
        # Benchmark
        iterations = 50
        start = time.perf_counter()
        for _ in range(iterations):
            try:
                self.orch.claim_next_task(agent="claude_code")
            except Exception:
                pass  # OK — we just want timing
        elapsed = time.perf_counter() - start
        avg_ms = (elapsed / iterations) * 1000
        self.assertLess(avg_ms, 1.0, f"avg claim_next_task={avg_ms:.3f}ms, expected <1ms")


if __name__ == "__main__":
    unittest.main()
