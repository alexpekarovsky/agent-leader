from __future__ import annotations

import unittest

from orchestrator.github_ci import normalize_github_ci_result


class GithubCiNormalizationTests(unittest.TestCase):
    def test_success_payload_maps_to_passed(self) -> None:
        payload = {
            "name": "backend-tests",
            "status": "completed",
            "conclusion": "success",
            "head_sha": "abc123",
            "head_branch": "main",
            "html_url": "https://github.com/org/repo/actions/runs/1",
            "run_id": 1,
            "run_attempt": 2,
            "passed": 120,
            "failed": 0,
        }
        result = normalize_github_ci_result(payload)
        self.assertEqual("passed", result["state"])
        self.assertEqual("success", result["conclusion"])
        self.assertEqual(120, result["passed"])
        self.assertEqual(0, result["failed"])

    def test_failure_payload_maps_to_failed(self) -> None:
        payload = {
            "workflow": "frontend-ci",
            "status": "completed",
            "conclusion": "failure",
            "sha": "def456",
            "branch": "feature/x",
            "url": "https://example.test/ci/2",
            "id": "42",
            "attempt": "1",
        }
        result = normalize_github_ci_result(payload)
        self.assertEqual("failed", result["state"])
        self.assertEqual("frontend-ci", result["name"])
        self.assertEqual(42, result["run_id"])
        self.assertEqual(1, result["attempt"])

    def test_running_payload_maps_to_running(self) -> None:
        payload = {"name": "lint", "status": "in_progress", "conclusion": None}
        result = normalize_github_ci_result(payload)
        self.assertEqual("running", result["state"])
        self.assertEqual("unknown", result["conclusion"])

    def test_unknown_payload_defaults(self) -> None:
        result = normalize_github_ci_result({})
        self.assertEqual("unknown", result["state"])
        self.assertEqual("ci", result["name"])
        self.assertIsNone(result["run_id"])
        self.assertIsNone(result["attempt"])


if __name__ == "__main__":
    unittest.main()
