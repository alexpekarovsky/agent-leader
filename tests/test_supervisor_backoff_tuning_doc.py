"""Static validation of docs/supervisor-restart-backoff-tuning.md.

Checks that tuning examples use valid supervisor flags, backoff
parameters are documented, and profiles are complete.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "supervisor-restart-backoff-tuning.md"
DOCS_DIR = REPO_ROOT / "docs"

VALID_FLAGS = {
    "--max-restarts", "--backoff-base", "--backoff-max",
    "--manager-interval", "--worker-interval",
    "--manager-cli-timeout", "--worker-cli-timeout",
    "--project-root", "--log-dir", "--pid-dir", "--help",
}

EXPECTED_PARAMS = [
    "--max-restarts",
    "--backoff-base",
    "--backoff-max",
]

EXPECTED_PROFILES = [
    "Fast local testing",
    "Unattended",
]


class SupervisorBackoffTuningDocTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        blocks = re.findall(r"```(?:bash)?\n(.*?)```", cls.content, re.DOTALL)
        cls.all_code = "\n".join(blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_supervisor_flags_valid(self) -> None:
        for line in self.all_code.splitlines():
            if "supervisor.sh" in line:
                flags = re.findall(r"(--[\w-]+)", line)
                for flag in flags:
                    self.assertIn(flag, VALID_FLAGS, f"unknown flag: {flag}")

    def test_backoff_parameters_documented(self) -> None:
        for param in EXPECTED_PARAMS:
            self.assertIn(param, self.content, f"missing param: {param}")

    def test_profiles_present(self) -> None:
        for profile in EXPECTED_PROFILES:
            self.assertIn(profile, self.content, f"missing profile: {profile}")

    def test_backoff_calculation_section(self) -> None:
        self.assertIn("Backoff calculation", self.content)
        self.assertIn("backoff_base", self.content)
        self.assertIn("backoff_max", self.content)

    def test_supervisor_commands_in_examples(self) -> None:
        commands = re.findall(r"supervisor\.sh\s+(\w+)", self.all_code)
        valid = {"start", "stop", "status", "restart", "clean"}
        for cmd in commands:
            self.assertIn(cmd, valid, f"invalid supervisor command: {cmd}")

    def test_parameter_reference_table(self) -> None:
        self.assertIn("Parameter reference", self.content)

    def test_doc_links_resolve(self) -> None:
        links = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        for link in links:
            target = DOCS_DIR / link
            self.assertTrue(target.exists(), f"link to {link} does not resolve")

    def test_no_duplicate_headers(self) -> None:
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        seen: set[str] = set()
        for h in headers:
            self.assertNotIn(h, seen, f"duplicate header: '{h}'")
            seen.add(h)


if __name__ == "__main__":
    unittest.main()
