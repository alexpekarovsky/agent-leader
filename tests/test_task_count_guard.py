from __future__ import annotations

import json
import os
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


class TaskCountGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.prev = os.environ.pop("ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK", None)
        self.orch = Orchestrator(root=self.root, policy=_make_policy(self.root / "policy.json"))
        self.orch.bootstrap()

    def tearDown(self) -> None:
        if self.prev is not None:
            os.environ["ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK"] = self.prev
        else:
            os.environ.pop("ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK", None)
        self._tmp.cleanup()

    def test_rejects_task_list_shrink_by_default(self) -> None:
        t1 = self.orch.create_task("t1", "backend", ["a"])
        self.orch.create_task("t2", "backend", ["b"])
        with self.assertRaises(RuntimeError) as ctx:
            self.orch._write_tasks_json([t1])
        self.assertIn("refusing_tasks_json_shrink", str(ctx.exception))
        self.assertEqual(2, len(self.orch.list_tasks()))

    def test_allows_task_list_shrink_with_explicit_override(self) -> None:
        t1 = self.orch.create_task("t1", "backend", ["a"])
        self.orch.create_task("t2", "backend", ["b"])
        os.environ["ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK"] = "1"
        self.orch._write_tasks_json([t1])
        self.assertEqual(1, len(self.orch.list_tasks()))


if __name__ == "__main__":
    unittest.main()
