"""Static validation of docs/timeout-semantics.md command snippets.

Checks that referenced scripts exist, flags are recognized, and
code block syntax is consistent.  No command execution required.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "timeout-semantics.md"

# Known flags per script
KNOWN_FLAGS: dict[str, set[str]] = {
    "manager_loop.sh": {
        "--once", "--cli", "--cli-timeout", "--log-dir",
        "--project-root", "--interval", "--max-logs",
    },
    "worker_loop.sh": {
        "--once", "--cli", "--agent", "--cli-timeout", "--log-dir",
        "--project-root", "--interval", "--max-logs",
    },
    "team_tmux.sh": {
        "--dry-run", "--session", "--manager-cli-timeout",
        "--worker-cli-timeout", "--log-dir", "--project-root",
        "--manager-interval", "--worker-interval",
    },
    "log_check.sh": {
        "--log-dir", "--strict", "--max-age-minutes",
    },
    "supervisor.sh": {
        "status", "start", "stop", "clean", "--pid-dir", "--log-dir",
        "--help",
    },
}


class TimeoutSemanticsDocTests(unittest.TestCase):
    """Static checks on timeout-semantics.md."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = DOC.read_text(encoding="utf-8")
        cls.code_blocks = re.findall(
            r"```(?:bash)?\n(.*?)```", cls.content, re.DOTALL
        )
        cls.all_code = "\n".join(cls.code_blocks)

    def test_doc_exists(self) -> None:
        self.assertTrue(DOC.exists())

    def test_referenced_scripts_exist(self) -> None:
        refs = re.findall(
            r"\./scripts/autopilot/(\S+\.sh)", self.all_code
        )
        for script in set(refs):
            path = REPO_ROOT / "scripts" / "autopilot" / script
            self.assertTrue(
                path.exists(),
                f"doc references {script} but it does not exist",
            )

    def test_flags_are_recognized(self) -> None:
        for script, flags in KNOWN_FLAGS.items():
            pattern = re.compile(
                rf"\./scripts/autopilot/{re.escape(script)}\b(.+?)(?:\n|$)",
            )
            for match in pattern.finditer(self.all_code):
                used = re.findall(r"(--[\w-]+)", match.group(1))
                for flag in used:
                    self.assertIn(
                        flag, flags,
                        f"unknown flag '{flag}' for {script}",
                    )

    def test_timeout_flag_names_in_tables(self) -> None:
        """Flags mentioned in markdown tables should be valid."""
        table_flags = re.findall(r"`(--[\w-]+)`", self.content)
        all_known = set()
        for flags in KNOWN_FLAGS.values():
            all_known.update(f for f in flags if f.startswith("--"))
        for flag in table_flags:
            self.assertIn(
                flag, all_known,
                f"table references unknown flag: {flag}",
            )

    def test_doc_links_resolve(self) -> None:
        refs = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        for ref in refs:
            # The incident-triage-order.md may not exist yet — skip it
            # since it's a known gap (blocked task).
            if "incident-triage" in ref:
                continue
            path = docs_dir / ref
            self.assertTrue(
                path.exists(),
                f"doc links to {ref} but it does not exist",
            )

    def test_no_duplicate_section_headers(self) -> None:
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        seen: set[str] = set()
        for h in headers:
            self.assertNotIn(h, seen, f"duplicate header: '{h}'")
            seen.add(h)


if __name__ == "__main__":
    unittest.main()
