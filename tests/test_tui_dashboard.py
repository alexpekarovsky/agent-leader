from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "autopilot" / "dashboard_tui.py"

spec = importlib.util.spec_from_file_location("dashboard_tui", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)  # type: ignore[arg-type]


class DashboardTuiTests(unittest.TestCase):
    def test_extract_token_usage_variants(self) -> None:
        p, c, t = mod._extract_token_usage({"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.assertEqual((p, c, t), (10, 5, 15))

        p, c, t = mod._extract_token_usage({"usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 20}})
        self.assertEqual((p, c, t), (7, 9, 20))

        p, c, t = mod._extract_token_usage({})
        self.assertEqual((p, c, t), (None, None, None))

    def test_build_snapshot_progress_budget_and_loc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "bus" / "reports").mkdir(parents=True, exist_ok=True)
            (root / ".autopilot-logs").mkdir(parents=True, exist_ok=True)

            project_root = "/tmp/my-project"
            tasks = [
                {"id": "T1", "project_root": project_root, "status": "done", "owner": "codex", "title": "Done"},
                {"id": "T2", "project_root": project_root, "status": "assigned", "owner": "gemini", "title": "Open"},
            ]
            (root / "state" / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            (root / "state" / "blockers.json").write_text("[]", encoding="utf-8")
            (root / "state" / "bugs.json").write_text("[]", encoding="utf-8")
            (root / "state" / "agents.json").write_text(
                json.dumps({"codex": {"status": "active", "last_seen": "2026-03-17T00:00:00+00:00", "metadata": {"instance_id": "codex#1"}}}),
                encoding="utf-8",
            )
            (root / "bus" / "events.jsonl").write_text("", encoding="utf-8")

            report = {
                "project_root": project_root,
                "commit_metrics": {"lines_added": 100, "lines_deleted": 30},
                "token_usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33},
            }
            (root / "bus" / "reports" / "TASK-T2.json").write_text(json.dumps(report), encoding="utf-8")

            stamp = mod._now_utc().strftime("%Y%m%d")
            (root / ".autopilot-logs" / f".budget-worker-codex-codex-{stamp}.count").write_text("17", encoding="utf-8")

            snap = mod.build_snapshot(project_root=project_root, root=root)

            self.assertEqual(snap.total_tasks, 2)
            self.assertEqual(snap.open_tasks, 1)
            self.assertEqual(snap.done_tasks, 1)
            self.assertEqual(snap.progress_percent, 50)
            self.assertEqual(snap.loc_added_total, 100)
            self.assertEqual(snap.loc_deleted_total, 30)
            self.assertEqual(snap.loc_net_total, 70)
            self.assertEqual(snap.budget_calls_today, 17)
            self.assertEqual(snap.token_total, 33)


if __name__ == "__main__":
    unittest.main()
