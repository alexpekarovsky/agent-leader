"""Static validation of docs/supervisor-demo-runbook.md.

Checks that supervisor commands use valid actions/flags and that
doc links resolve.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-demo-runbook.md"

VALID_ACTIONS = {"start", "stop", "status", "restart", "clean"}
VALID_FLAGS = {
    "--project-root", "--log-dir", "--pid-dir",
    "--manager-cli-timeout", "--worker-cli-timeout",
    "--manager-interval", "--worker-interval",
    "--max-restarts", "--backoff-base", "--backoff-max",
    "--help",
}
EXPECTED_LABELS = {"manager", "claude", "gemini", "watchdog"}


class SupervisorDemoRunbookTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_supervisor_actions_valid(self) -> None:
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.all_code)
        for action in actions:
            self.assertIn(action, VALID_ACTIONS, f"unknown action: {action}")

    def test_supervisor_flags_valid(self) -> None:
        for line in self.all_code.splitlines():
            if "supervisor.sh" in line:
                flags = re.findall(r"(--[\w-]+)", line)
                for flag in flags:
                    self.assertIn(flag, VALID_FLAGS, f"unknown flag: {flag}")

    def test_expected_process_labels_in_output(self) -> None:
        for label in EXPECTED_LABELS:
            self.assertIn(label, self.content, f"missing process label: {label}")

    def test_expected_status_values_documented(self) -> None:
        for status in ("stopped", "running"):
            self.assertIn(status, self.content)

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        for link in links:
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )

    def test_demo_flow_steps_present(self) -> None:
        for step in ("clean state", "Start all", "Check status",
                      "Inspect logs", "Stop all", "Clean up"):
            self.assertTrue(
                any(step.lower() in line.lower() for line in self.content.splitlines()),
                f"missing demo step: {step}",
            )


if __name__ == "__main__":
    unittest.main()
