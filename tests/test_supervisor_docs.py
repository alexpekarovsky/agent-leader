"""Cross-link and command consistency checks for supervisor-related docs.

Validates that supervisor docs reference each other correctly and that
command snippets use valid supervisor.sh actions and flags.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

SUPERVISOR_DOCS = [
    "supervisor-cli-spec.md",
    "supervisor-test-plan.md",
    "tmux-vs-supervisor.md",
]

VALID_ACTIONS = {"start", "stop", "status", "restart", "clean"}
VALID_FLAGS = {
    "--project-root", "--log-dir", "--pid-dir",
    "--manager-cli-timeout", "--worker-cli-timeout",
    "--manager-interval", "--worker-interval",
    "--max-restarts", "--backoff-base", "--backoff-max",
    "--help",
}


class SupervisorDocsCrossLinkTests(unittest.TestCase):
    """Validate cross-references between supervisor docs."""

    def test_all_supervisor_docs_exist(self) -> None:
        for name in SUPERVISOR_DOCS:
            self.assertTrue((DOCS_DIR / name).exists(), f"missing: {name}")

    def test_spec_links_to_test_plan(self) -> None:
        content = (DOCS_DIR / "supervisor-cli-spec.md").read_text(encoding="utf-8")
        self.assertIn("supervisor-test-plan.md", content)

    def test_test_plan_references_spec_or_script(self) -> None:
        content = (DOCS_DIR / "supervisor-test-plan.md").read_text(encoding="utf-8")
        self.assertTrue(
            "supervisor.sh" in content or "supervisor-cli-spec" in content,
            "test plan should reference supervisor.sh or cli spec",
        )

    def test_tmux_vs_supervisor_links_to_spec(self) -> None:
        content = (DOCS_DIR / "tmux-vs-supervisor.md").read_text(encoding="utf-8")
        self.assertIn("supervisor-cli-spec.md", content)

    def test_all_doc_internal_links_resolve(self) -> None:
        for name in SUPERVISOR_DOCS:
            content = (DOCS_DIR / name).read_text(encoding="utf-8")
            links = re.findall(r"\[.*?\]\((\S+?\.md)\)", content)
            for link in links:
                path = DOCS_DIR / link
                self.assertTrue(path.exists(), f"{name} -> {link} does not exist")


class SupervisorDocsCommandTests(unittest.TestCase):
    """Validate command snippets in supervisor docs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.all_code = ""
        for name in SUPERVISOR_DOCS:
            content = (DOCS_DIR / name).read_text(encoding="utf-8")
            blocks = re.findall(r"```(?:bash)?\n(.*?)```", content, re.DOTALL)
            cls.all_code += "\n".join(blocks) + "\n"

    def test_supervisor_actions_are_valid(self) -> None:
        """supervisor.sh <action> should use known actions."""
        actions = re.findall(r"supervisor\.sh\s+(\w+)", self.all_code)
        for action in actions:
            self.assertIn(
                action, VALID_ACTIONS,
                f"unknown supervisor action in docs: {action}",
            )

    def test_supervisor_flags_are_valid(self) -> None:
        # Find lines with supervisor.sh and extract flags
        for line in self.all_code.splitlines():
            if "supervisor.sh" in line:
                flags = re.findall(r"(--[\w-]+)", line)
                for flag in flags:
                    self.assertIn(
                        flag, VALID_FLAGS,
                        f"unknown supervisor flag in docs: {flag}",
                    )

    def test_spec_documents_all_actions(self) -> None:
        content = (DOCS_DIR / "supervisor-cli-spec.md").read_text(encoding="utf-8")
        for action in VALID_ACTIONS:
            self.assertIn(action, content, f"spec missing action: {action}")


if __name__ == "__main__":
    unittest.main()
