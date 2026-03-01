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


class LeanTaskProfileTests(unittest.TestCase):
    def test_create_task_sets_default_delivery_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "policy.json"))
            orch.bootstrap()

            task = orch.create_task(
                title="Lean defaults",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
            )

            self.assertEqual(
                {"risk": "medium", "test_plan": "targeted", "doc_impact": "none"},
                task.get("delivery_profile"),
            )

    def test_create_task_accepts_explicit_delivery_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "policy.json"))
            orch.bootstrap()

            task = orch.create_task(
                title="Lean explicit",
                workstream="backend",
                acceptance_criteria=["done"],
                owner="claude_code",
                risk="high",
                test_plan="smoke",
                doc_impact="runbook",
            )

            self.assertEqual(
                {"risk": "high", "test_plan": "smoke", "doc_impact": "runbook"},
                task.get("delivery_profile"),
            )

    def test_create_task_rejects_invalid_delivery_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = Orchestrator(root=root, policy=_make_policy(root / "policy.json"))
            orch.bootstrap()

            with self.assertRaises(ValueError):
                orch.create_task(
                    title="Lean invalid",
                    workstream="backend",
                    acceptance_criteria=["done"],
                    owner="claude_code",
                    risk="extreme",
                )


if __name__ == "__main__":
    unittest.main()
