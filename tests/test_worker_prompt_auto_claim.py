"""Test that worker_loop.sh prompt checks auto_claimed_task before poll+claim.

Validates acceptance criteria for TASK-5533f888: the generated worker prompt
must instruct the LLM to check the connect response's auto_claimed_task field
before calling poll_events or claim_next_task, avoiding redundant calls.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_LOOP = REPO_ROOT / "scripts" / "autopilot" / "worker_loop.sh"


def _extract_prompt_template(script_text: str) -> str:
    """Extract the heredoc prompt template from worker_loop.sh."""
    # Match the cat >"$prompt_file" <<EOF ... EOF block
    match = re.search(
        r'cat\s*>"?\$prompt_file"?\s*<<EOF\n(.*?)\nEOF',
        script_text,
        re.DOTALL,
    )
    assert match, "Could not find prompt template heredoc in worker_loop.sh"
    return match.group(1)


class WorkerPromptAutoClaimTests(unittest.TestCase):
    """Verify the worker prompt instructs single-claim-path behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = WORKER_LOOP.read_text(encoding="utf-8")
        cls.prompt = _extract_prompt_template(cls.script_text)

    def test_prompt_mentions_auto_claimed_task(self) -> None:
        """Prompt must reference auto_claimed_task from connect response."""
        self.assertIn("auto_claimed_task", self.prompt)

    def test_auto_claim_check_before_poll_events(self) -> None:
        """auto_claimed_task check must appear before poll_events call."""
        auto_claim_pos = self.prompt.find("auto_claimed_task")
        poll_pos = self.prompt.find("poll_events")
        self.assertGreater(auto_claim_pos, -1, "auto_claimed_task not found")
        self.assertGreater(poll_pos, -1, "poll_events not found")
        self.assertLess(auto_claim_pos, poll_pos,
                        "auto_claimed_task check must come before poll_events")

    def test_auto_claim_check_before_claim_next_task(self) -> None:
        """auto_claimed_task check must appear before claim_next_task call."""
        auto_claim_pos = self.prompt.find("auto_claimed_task")
        claim_pos = self.prompt.find("claim_next_task")
        self.assertGreater(auto_claim_pos, -1, "auto_claimed_task not found")
        self.assertGreater(claim_pos, -1, "claim_next_task not found")
        self.assertLess(auto_claim_pos, claim_pos,
                        "auto_claimed_task check must come before claim_next_task")

    def test_prompt_instructs_skip_on_auto_claim(self) -> None:
        """Prompt must instruct skipping poll+claim when task is auto-claimed."""
        # Should contain language about skipping/using the auto-claimed task directly
        self.assertTrue(
            "skip" in self.prompt.lower() or "use it directly" in self.prompt.lower(),
            "Prompt must instruct to skip redundant calls when auto_claimed_task is present",
        )


if __name__ == "__main__":
    unittest.main()
