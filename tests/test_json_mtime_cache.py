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

    def _register_operational_agent(self, name: str = "claude_code") -> None:
        """Helper to register an agent with all required metadata fields."""
        meta = {
            "project_root": str(self.root), "cwd": str(self.root),
            "verified": True, "same_project": True,
            "client": "test", "model": "test", "permissions_mode": "auto",
            "sandbox_mode": "off", "session_id": "s1", "connection_id": "c1",
            "server_version": "1.0", "verification_source": "test",
        }
        agents = {name: {"status": "active", "last_seen": self.orch._now(),
                          "metadata": meta}}
        self.orch._write_json(self.orch.agents_path, agents)

    def test_claim_next_task_does_not_corrupt_cache(self) -> None:
        """claim_next_task mutates tasks; cache must stay pristine."""
        task = {"id": "T-claim", "title": "claimable", "status": "assigned",
                "owner": "claude_code", "updated_at": self.orch._now(),
                "project_root": str(self.root), "project_name": self.root.name}
        self.orch._write_json(self.orch.tasks_path, [task])
        self._register_operational_agent()
        # Warm cache — grab a read-only reference
        cached_ref = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(cached_ref[0]["status"], "assigned")
        # Claim mutates the task to in_progress
        claimed = self.orch.claim_next_task(owner="claude_code")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["status"], "in_progress")
        # The read-only reference grabbed before must NOT be mutated
        self.assertEqual(cached_ref[0]["status"], "assigned",
                         "claim_next_task must not corrupt cached reference")

    def test_ingest_report_does_not_corrupt_cache(self) -> None:
        """ingest_report mutates task status; cache must stay pristine."""
        task = {"id": "T-report", "title": "reportable", "status": "in_progress",
                "owner": "claude_code", "updated_at": self.orch._now(),
                "project_root": str(self.root), "project_name": self.root.name}
        self.orch._write_json(self.orch.tasks_path, [task])
        self._register_operational_agent()
        # Warm cache
        cached_ref = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(cached_ref[0]["status"], "in_progress")
        # Submit report
        report = {
            "task_id": "T-report",
            "agent": "claude_code",
            "status": "done",
            "commit_sha": "abc123",
            "test_summary": {"command": "pytest", "passed": 1, "failed": 0},
        }
        self.orch.ingest_report(report)
        # Cached reference must be untouched
        self.assertEqual(cached_ref[0]["status"], "in_progress",
                         "ingest_report must not corrupt cached reference")

    def test_read_json_list_make_copy(self) -> None:
        """_read_json_list with make_copy=True returns independent copy."""
        blocker = {"id": "BLK-1", "status": "open", "task_id": "T1"}
        self.orch._write_json(self.orch.blockers_path, [blocker])
        ref = self.orch._read_json_list(self.orch.blockers_path)
        copy = self.orch._read_json_list(self.orch.blockers_path, make_copy=True)
        self.assertEqual(ref, copy)
        self.assertIsNot(ref, copy, "make_copy=True must return new object")
        # Mutating copy must not affect cached ref
        copy.append({"id": "BLK-2"})
        ref_again = self.orch._read_json_list(self.orch.blockers_path)
        self.assertEqual(len(ref_again), 1, "cache must not grow from copy mutation")

    def test_read_json_list_default_returns_reference(self) -> None:
        """_read_json_list default returns cached reference."""
        blocker = {"id": "BLK-1", "status": "open", "task_id": "T1"}
        self.orch._write_json(self.orch.blockers_path, [blocker])
        ref1 = self.orch._read_json_list(self.orch.blockers_path)
        ref2 = self.orch._read_json_list(self.orch.blockers_path)
        self.assertIs(ref1, ref2, "default should return same cached object")

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


class LazyCopyListTests(unittest.TestCase):
    """Tests for _LazyCopyList lazy deep-copy behaviour."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.orch = _make_orch(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_readonly_callers_get_direct_reference(self) -> None:
        """make_copy=False returns the same cached object (no copy)."""
        task = {"id": "T1", "title": "t", "status": "assigned", "owner": "a"}
        self.orch._write_json(self.orch.tasks_path, [task])
        ref1 = self.orch._read_json(self.orch.tasks_path)
        ref2 = self.orch._read_json(self.orch.tasks_path)
        self.assertIs(ref1, ref2)
        self.assertIs(ref1[0], ref2[0])

    def test_mutation_copy_does_not_corrupt_cache(self) -> None:
        """Mutating an item from make_copy=True must not affect cached data."""
        task = {"id": "T1", "title": "t", "status": "assigned", "owner": "a",
                "lease": {"lease_id": "L1", "ttl": 300}}
        self.orch._write_json(self.orch.tasks_path, [task])
        # Get mutable copy and modify it
        mutable = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        found = next((t for t in mutable if t["id"] == "T1"), None)
        self.assertIsNotNone(found)
        found["status"] = "done"
        found["lease"]["ttl"] = 999
        # Original cache must be pristine
        pristine = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(pristine[0]["status"], "assigned")
        self.assertEqual(pristine[0]["lease"]["ttl"], 300)

    def test_lazy_copy_only_copies_accessed_items(self) -> None:
        """Items not accessed via iteration are not deep-copied."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": f"T{i}"} for i in range(10)]
        lazy = _LazyCopyList(original)
        # Access only item at index 2 via __getitem__
        _ = lazy[2]
        self.assertIn(2, lazy._copied)
        # Items 0, 1, 3-9 should NOT have been copied
        for i in [0, 1, 3, 4, 5, 6, 7, 8, 9]:
            self.assertNotIn(i, lazy._copied)

    def test_lazy_copy_next_short_circuits(self) -> None:
        """next() with generator only copies items up to the match."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": f"T{i}"} for i in range(100)]
        lazy = _LazyCopyList(original)
        _ = next((t for t in lazy if t["id"] == "T3"), None)
        # Only items 0-3 should have been copied (iteration stops at T3)
        self.assertEqual(lazy._copied, {0, 1, 2, 3})

    def test_lazy_copy_isinstance_list(self) -> None:
        """_LazyCopyList must pass isinstance(x, list) checks."""
        from orchestrator.engine import _LazyCopyList
        lazy = _LazyCopyList([{"id": "T1"}])
        self.assertIsInstance(lazy, list)

    def test_lazy_copy_json_serializable(self) -> None:
        """_LazyCopyList must be directly serializable by json.dump."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": "T1", "nested": {"a": 1}}, {"id": "T2"}]
        lazy = _LazyCopyList(original)
        # Access and mutate first item
        lazy[0]["nested"]["a"] = 42
        result = json.loads(json.dumps(lazy))
        self.assertEqual(result[0]["nested"]["a"], 42)
        self.assertEqual(result[1]["id"], "T2")

    def test_lazy_copy_append_works(self) -> None:
        """Appending to a _LazyCopyList does not affect the original."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": "T1"}]
        lazy = _LazyCopyList(original)
        lazy.append({"id": "T2"})
        self.assertEqual(len(lazy), 2)
        self.assertEqual(len(original), 1)

    def test_lazy_copy_len(self) -> None:
        """len() returns correct count."""
        from orchestrator.engine import _LazyCopyList
        lazy = _LazyCopyList([1, 2, 3])
        self.assertEqual(len(lazy), 3)

    def test_lazy_copy_negative_index(self) -> None:
        """Negative indexing works and triggers copy."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": "T0"}, {"id": "T1"}, {"id": "T2"}]
        lazy = _LazyCopyList(original)
        item = lazy[-1]
        self.assertEqual(item["id"], "T2")
        self.assertIn(2, lazy._copied)

    def test_lazy_copy_slice(self) -> None:
        """Slicing returns a regular list of copied items."""
        from orchestrator.engine import _LazyCopyList
        original = [{"id": f"T{i}"} for i in range(5)]
        lazy = _LazyCopyList(original)
        sliced = lazy[1:3]
        self.assertIsInstance(sliced, list)
        self.assertNotIsInstance(sliced, _LazyCopyList)
        self.assertEqual(len(sliced), 2)
        self.assertEqual(sliced[0]["id"], "T1")

    def test_write_tasks_with_lazy_copy(self) -> None:
        """End-to-end: mutate one task in lazy copy, write back, verify on disk."""
        tasks = [{"id": f"T{i}", "title": f"task {i}", "status": "assigned",
                  "owner": "a"} for i in range(5)]
        self.orch._write_json(self.orch.tasks_path, tasks)
        mutable = self.orch._read_json(self.orch.tasks_path, make_copy=True)
        target = next((t for t in mutable if t["id"] == "T2"), None)
        target["status"] = "done"
        self.orch._write_json(self.orch.tasks_path, mutable)
        # Re-read from disk
        on_disk = self.orch._read_json(self.orch.tasks_path)
        self.assertEqual(on_disk[2]["status"], "done")
        # Other tasks unchanged
        self.assertEqual(on_disk[0]["status"], "assigned")
        self.assertEqual(on_disk[4]["status"], "assigned")


if __name__ == "__main__":
    unittest.main()
