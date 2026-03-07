from __future__ import annotations

import json
import unittest
from pathlib import Path

from orchestrator.policy import Policy


class PolicyBundlePresetTests(unittest.TestCase):
    def test_bundle_files_exist_and_load(self) -> None:
        config = Path(__file__).resolve().parents[1] / "config"
        bundle_paths = [
            config / "policy.strict-qa.json",
            config / "policy.prototype-fast.json",
            config / "policy.balanced.json",
        ]
        for path in bundle_paths:
            self.assertTrue(path.exists(), f"missing bundle: {path.name}")
            policy = Policy.load(path)
            self.assertTrue(policy.name)
            self.assertTrue(policy.manager())
            self.assertIsInstance(policy.routing, dict)
            self.assertIn("default", policy.routing)

    def test_balanced_bundle_defaults_to_consensus(self) -> None:
        config = Path(__file__).resolve().parents[1] / "config"
        data = json.loads((config / "policy.balanced.json").read_text(encoding="utf-8"))
        self.assertEqual("balanced", data["name"])
        self.assertEqual("consensus", data["decisions"]["architecture"]["mode"])


if __name__ == "__main__":
    unittest.main()
