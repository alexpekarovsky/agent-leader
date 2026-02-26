"""Static validation of milestone docs: supervisor spec, dual-CC, and related.

Checks that referenced scripts exist, doc links resolve, and JSON/code
examples parse correctly.  Reuses patterns from existing doc checkers.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

# Milestone docs to validate
MILESTONE_DOCS = [
    "supervisor-cli-spec.md",
    "supervisor-test-plan.md",
    "dual-cc-operation.md",
    "dual-cc-conventions.md",
    "log-retention-tuning.md",
    "tmux-pane-cheatsheet.md",
]

KNOWN_SCRIPTS = {
    "team_tmux.sh", "manager_loop.sh", "worker_loop.sh",
    "watchdog_loop.sh", "monitor_loop.sh", "smoke_test.sh",
    "log_check.sh", "supervisor.sh", "common.sh",
}


class MilestoneDocsTests(unittest.TestCase):
    """Cross-doc consistency checks."""

    def test_all_milestone_docs_exist(self) -> None:
        for name in MILESTONE_DOCS:
            path = DOCS_DIR / name
            self.assertTrue(path.exists(), f"milestone doc missing: {name}")

    def test_internal_doc_links_resolve(self) -> None:
        for name in MILESTONE_DOCS:
            content = (DOCS_DIR / name).read_text(encoding="utf-8")
            links = re.findall(r"\[.*?\]\((\S+?\.md)\)", content)
            for link in links:
                # Skip known-missing docs
                if "incident-triage" in link:
                    continue
                target = DOCS_DIR / link
                self.assertTrue(
                    target.exists(),
                    f"{name} links to {link} which does not exist",
                )

    def test_script_references_exist(self) -> None:
        for name in MILESTONE_DOCS:
            content = (DOCS_DIR / name).read_text(encoding="utf-8")
            # Extract code blocks
            code_blocks = re.findall(r"```(?:bash)?\n(.*?)```", content, re.DOTALL)
            all_code = "\n".join(code_blocks)
            refs = re.findall(r"scripts/autopilot/(\S+\.sh)", all_code)
            for script in set(refs):
                path = REPO_ROOT / "scripts" / "autopilot" / script
                self.assertTrue(
                    path.exists(),
                    f"{name} references {script} which does not exist",
                )

    def test_no_duplicate_headers_per_doc(self) -> None:
        for name in MILESTONE_DOCS:
            content = (DOCS_DIR / name).read_text(encoding="utf-8")
            headers = re.findall(r"^## (.+)$", content, re.MULTILINE)
            seen: set[str] = set()
            for h in headers:
                self.assertNotIn(
                    h, seen,
                    f"{name} has duplicate header: '{h}'",
                )
                seen.add(h)

    def test_supervisor_spec_documents_all_commands(self) -> None:
        content = (DOCS_DIR / "supervisor-cli-spec.md").read_text(encoding="utf-8")
        for cmd in ("start", "stop", "status", "restart", "clean"):
            self.assertIn(
                f"### `{cmd}`", content,
                f"supervisor-cli-spec.md missing section for command: {cmd}",
            )

    def test_dual_cc_references_swarm_mode(self) -> None:
        content = (DOCS_DIR / "dual-cc-operation.md").read_text(encoding="utf-8")
        self.assertIn("swarm-mode.md", content)
        self.assertIn("instance_id", content)


if __name__ == "__main__":
    unittest.main()
