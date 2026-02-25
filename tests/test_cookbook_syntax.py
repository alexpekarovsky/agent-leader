"""Static validation of docs/autopilot-command-cookbook.md examples.

Checks that referenced scripts exist and recognized flags are spelled
correctly.  Does NOT execute the commands — purely regex/path based.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COOKBOOK = REPO_ROOT / "docs" / "autopilot-command-cookbook.md"

# Scripts that should exist under scripts/autopilot/
KNOWN_SCRIPTS = {
    "team_tmux.sh",
    "manager_loop.sh",
    "worker_loop.sh",
    "watchdog_loop.sh",
    "monitor_loop.sh",
    "smoke_test.sh",
    "log_check.sh",
    "supervisor.sh",
    "common.sh",
}

# Known flags per script (subset — only what cookbook uses)
KNOWN_FLAGS: dict[str, set[str]] = {
    "team_tmux.sh": {
        "--dry-run", "--session", "--manager-cli-timeout",
        "--worker-cli-timeout", "--log-dir", "--project-root",
        "--manager-interval", "--worker-interval",
    },
    "manager_loop.sh": {
        "--once", "--cli", "--cli-timeout", "--log-dir",
        "--project-root", "--interval", "--max-logs",
    },
    "worker_loop.sh": {
        "--once", "--cli", "--agent", "--cli-timeout", "--log-dir",
        "--project-root", "--interval", "--max-logs",
    },
    "watchdog_loop.sh": {
        "--once", "--log-dir", "--project-root", "--interval",
        "--max-logs", "--assigned-timeout", "--inprogress-timeout",
        "--reported-timeout",
    },
    "log_check.sh": {
        "--log-dir", "--strict", "--max-age-minutes",
    },
    "supervisor.sh": {
        "status", "start", "stop", "clean", "--pid-dir", "--log-dir",
        "--help",
    },
}


class CookbookSyntaxTests(unittest.TestCase):
    """Static checks on cookbook command examples."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = COOKBOOK.read_text(encoding="utf-8")
        # Extract fenced code block contents
        cls.code_blocks = re.findall(
            r"```(?:bash)?\n(.*?)```", cls.content, re.DOTALL
        )
        cls.all_code = "\n".join(cls.code_blocks)

    def test_cookbook_file_exists(self) -> None:
        self.assertTrue(COOKBOOK.exists())

    def test_referenced_scripts_exist(self) -> None:
        """Every ./scripts/autopilot/*.sh reference should be a real file."""
        refs = re.findall(
            r"\./scripts/autopilot/(\S+\.sh)", self.all_code
        )
        for script in set(refs):
            path = REPO_ROOT / "scripts" / "autopilot" / script
            self.assertTrue(
                path.exists(),
                f"cookbook references {script} but it does not exist at {path}",
            )

    def test_script_names_are_known(self) -> None:
        """No typos in script names."""
        refs = re.findall(
            r"\./scripts/autopilot/(\S+\.sh)", self.all_code
        )
        for script in set(refs):
            self.assertIn(
                script,
                KNOWN_SCRIPTS,
                f"cookbook references unknown script: {script}",
            )

    def test_flags_are_known_for_scripts(self) -> None:
        """Flags used in cookbook match known flags for each script."""
        for script, flags in KNOWN_FLAGS.items():
            # Find lines that invoke this script
            pattern = re.compile(
                rf"\./scripts/autopilot/{re.escape(script)}\b(.+?)(?:\n|$)",
            )
            for match in pattern.finditer(self.all_code):
                line_rest = match.group(1)
                # Handle continuation lines (backslash)
                used_flags = re.findall(r"(--[\w-]+)", line_rest)
                for flag in used_flags:
                    self.assertIn(
                        flag,
                        flags,
                        f"cookbook uses unknown flag '{flag}' for {script}",
                    )

    def test_no_duplicate_section_headers(self) -> None:
        """Each ## section header should be unique."""
        headers = re.findall(r"^## (.+)$", self.content, re.MULTILINE)
        seen: set[str] = set()
        for h in headers:
            self.assertNotIn(h, seen, f"duplicate section header: '{h}'")
            seen.add(h)

    def test_references_section_links_exist(self) -> None:
        """Markdown links in References point to existing docs."""
        refs = re.findall(r"\[.*?\]\((\S+?\.md)\)", self.content)
        docs_dir = REPO_ROOT / "docs"
        for ref in refs:
            path = docs_dir / ref
            self.assertTrue(
                path.exists(),
                f"cookbook links to {ref} but it does not exist",
            )


if __name__ == "__main__":
    unittest.main()
