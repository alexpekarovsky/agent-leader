"""Static validation of docs/supervisor-restart-backoff-tuning.md.

Checks command examples, flag names, and backoff parameters.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-restart-backoff-tuning.md"

VALID_FLAGS = {
    "--project-root", "--log-dir", "--pid-dir",
    "--manager-cli-timeout", "--worker-cli-timeout",
    "--manager-interval", "--worker-interval",
    "--max-restarts", "--backoff-base", "--backoff-max",
    "--help",
}


class SupervisorBackoffTuningTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_flags_valid(self) -> None:
        for line in self.content.splitlines():
            if "supervisor.sh" in line or line.strip().startswith("--"):
                flags = re.findall(r"(--[\w-]+)", line)
                for flag in flags:
                    self.assertIn(flag, VALID_FLAGS,
                                  f"unknown flag: {flag}")

    def test_backoff_parameters_documented(self) -> None:
        for param in ("--max-restarts", "--backoff-base", "--backoff-max"):
            self.assertIn(param, self.content,
                          f"missing parameter: {param}")

    def test_profiles_present(self) -> None:
        profiles_found = 0
        for keyword in ("fast", "unattended", "overnight"):
            if any(keyword.lower() in line.lower()
                   for line in self.content.splitlines()):
                profiles_found += 1
        self.assertGreaterEqual(profiles_found, 2,
                                "fewer than 2 tuning profiles")

    def test_backoff_formula(self) -> None:
        self.assertTrue(
            "backoff" in self.content.lower() and "2^" in self.content,
            "missing exponential backoff formula",
        )

    def test_auto_restart_caveat(self) -> None:
        self.assertTrue(
            any("auto-restart" in line.lower() or "auto restart" in line.lower()
                for line in self.content.splitlines()),
            "missing auto-restart caveat note",
        )

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        for link in links:
            self.assertTrue(
                (docs_dir / link).exists(),
                f"link to {link} does not resolve",
            )


if __name__ == "__main__":
    unittest.main()
