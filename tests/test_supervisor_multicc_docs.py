"""Cross-doc validation for AUTO-M1 supervisor and multi-CC docs.

Checks that command examples reference valid orchestrator API names,
task ID patterns are well-formed, script references exist, and doc
links resolve across the docs created in the AUTO-M1 ops stream.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

# AUTO-M1 docs to cross-validate
TARGET_DOCS = [
    "supervisor-cli-spec.md",
    "supervisor-test-plan.md",
    "supervisor-smoke-test-checklist.md",
    "supervisor-restart-backoff-tuning.md",
    "dual-cc-operation.md",
    "dual-cc-conventions.md",
]

# Valid orchestrator API function names that may appear in examples
VALID_ORCHESTRATOR_APIS = {
    "orchestrator_bootstrap",
    "orchestrator_register_agent",
    "orchestrator_connect_to_leader",
    "orchestrator_connect_team_members",
    "orchestrator_heartbeat",
    "orchestrator_get_roles",
    "orchestrator_set_role",
    "orchestrator_create_task",
    "orchestrator_list_tasks",
    "orchestrator_get_tasks_for_agent",
    "orchestrator_claim_next_task",
    "orchestrator_set_claim_override",
    "orchestrator_update_task_status",
    "orchestrator_submit_report",
    "orchestrator_validate_task",
    "orchestrator_list_agents",
    "orchestrator_discover_agents",
    "orchestrator_status",
    "orchestrator_guide",
    "orchestrator_publish_event",
    "orchestrator_poll_events",
    "orchestrator_ack_event",
    "orchestrator_raise_blocker",
    "orchestrator_list_blockers",
    "orchestrator_resolve_blocker",
    "orchestrator_list_bugs",
    "orchestrator_reassign_stale_tasks",
    "orchestrator_dedupe_tasks",
    "orchestrator_manager_cycle",
    "orchestrator_live_status_report",
    "orchestrator_get_agent_cursor",
    "orchestrator_decide_architecture",
}

# Valid supervisor.sh commands
VALID_SUPERVISOR_COMMANDS = {"start", "stop", "status", "restart", "clean"}

# Task ID pattern: real IDs use hex (TASK-abcdef12), examples may use
# short placeholders (TASK-aaa, TASK-xxx) which are also acceptable.
TASK_ID_RE = re.compile(r"TASK-[a-z0-9]{3,}")


class SupervisorMultiCCDocsTests(unittest.TestCase):
    """Cross-doc consistency checks for AUTO-M1 supervisor and multi-CC docs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc_contents: dict[str, str] = {}
        for name in TARGET_DOCS:
            path = DOCS_DIR / name
            if path.exists():
                cls.doc_contents[name] = path.read_text(encoding="utf-8")

    def test_all_target_docs_exist(self) -> None:
        for name in TARGET_DOCS:
            path = DOCS_DIR / name
            self.assertTrue(path.exists(), f"AUTO-M1 doc missing: {name}")

    def test_orchestrator_api_references_valid(self) -> None:
        """All orchestrator_* function calls in examples use known API names."""
        for name, content in self.doc_contents.items():
            refs = re.findall(r"\b(orchestrator_\w+)\b", content)
            for ref in refs:
                self.assertIn(
                    ref,
                    VALID_ORCHESTRATOR_APIS,
                    f"{name}: unknown orchestrator API '{ref}'",
                )

    def test_supervisor_commands_valid(self) -> None:
        """supervisor.sh commands in code blocks are valid."""
        for name, content in self.doc_contents.items():
            blocks = re.findall(r"```(?:bash)?\n(.*?)```", content, re.DOTALL)
            all_code = "\n".join(blocks)
            commands = re.findall(r"supervisor\.sh\s+(\w+)", all_code)
            for cmd in commands:
                self.assertIn(
                    cmd,
                    VALID_SUPERVISOR_COMMANDS,
                    f"{name}: invalid supervisor command '{cmd}'",
                )

    def test_task_id_format(self) -> None:
        """Task ID references follow TASK-{hex} pattern."""
        for name, content in self.doc_contents.items():
            # Find anything that looks like TASK-something
            candidates = re.findall(r"TASK-\S+", content)
            for candidate in candidates:
                # Strip trailing punctuation
                candidate = candidate.rstrip(",.;:)\"'`")
                self.assertRegex(
                    candidate,
                    TASK_ID_RE,
                    f"{name}: malformed task ID '{candidate}'",
                )

    def test_doc_links_resolve(self) -> None:
        """All markdown doc links point to existing files."""
        for name, content in self.doc_contents.items():
            links = re.findall(r"\[.*?\]\((\S+?\.md)\)", content)
            for link in links:
                target = DOCS_DIR / link
                self.assertTrue(
                    target.exists(),
                    f"{name}: link to '{link}' does not resolve",
                )

    def test_no_duplicate_headers_per_doc(self) -> None:
        for name, content in self.doc_contents.items():
            headers = re.findall(r"^## (.+)$", content, re.MULTILINE)
            seen: set[str] = set()
            for h in headers:
                self.assertNotIn(
                    h, seen,
                    f"{name}: duplicate header '{h}'",
                )
                seen.add(h)

    def test_script_references_in_code_blocks(self) -> None:
        """Shell script references in code blocks point to existing files."""
        for name, content in self.doc_contents.items():
            blocks = re.findall(r"```(?:bash)?\n(.*?)```", content, re.DOTALL)
            all_code = "\n".join(blocks)
            refs = re.findall(r"scripts/autopilot/(\S+\.sh)", all_code)
            for script in set(refs):
                path = REPO_ROOT / "scripts" / "autopilot" / script
                self.assertTrue(
                    path.exists(),
                    f"{name}: references script '{script}' which does not exist",
                )

    def test_dual_cc_docs_reference_instance_id(self) -> None:
        """Both dual-CC docs mention instance_id for Phase B context."""
        for name in ("dual-cc-operation.md", "dual-cc-conventions.md"):
            content = self.doc_contents.get(name, "")
            self.assertIn(
                "instance_id",
                content,
                f"{name}: should reference instance_id for Phase B context",
            )

    def test_supervisor_docs_reference_supervisor_sh(self) -> None:
        """Supervisor docs mention the supervisor.sh script."""
        for name in ("supervisor-cli-spec.md", "supervisor-test-plan.md",
                      "supervisor-smoke-test-checklist.md"):
            content = self.doc_contents.get(name, "")
            self.assertIn(
                "supervisor.sh",
                content,
                f"{name}: should reference supervisor.sh",
            )


if __name__ == "__main__":
    unittest.main()
