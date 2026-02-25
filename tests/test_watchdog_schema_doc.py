"""Static validation of docs/watchdog-jsonl-schema.md examples.

Extracts JSON snippets from the doc and verifies they parse correctly
and contain the documented key fields.  No live watchdog run required.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DOC = REPO_ROOT / "docs" / "watchdog-jsonl-schema.md"

# Required fields per event kind, from the doc's field tables.
REQUIRED_FIELDS: dict[str, set[str]] = {
    "stale_task": {
        "timestamp", "kind", "task_id", "owner", "status",
        "age_seconds", "timeout_seconds", "title",
    },
    "state_corruption_detected": {
        "timestamp", "kind", "path", "previous_type", "expected_type",
    },
}


class WatchdogSchemaDocTests(unittest.TestCase):
    """Validate JSON examples in the watchdog JSONL schema doc."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = SCHEMA_DOC.read_text(encoding="utf-8")
        # Extract all ```json ... ``` blocks
        cls.json_blocks = re.findall(
            r"```json\n(.*?)```", cls.content, re.DOTALL
        )

    def test_doc_exists(self) -> None:
        self.assertTrue(SCHEMA_DOC.exists())

    def test_json_examples_are_present(self) -> None:
        self.assertGreaterEqual(
            len(self.json_blocks), 2,
            "expected at least 2 JSON examples (stale_task + state_corruption)",
        )

    def test_all_json_examples_parse(self) -> None:
        for i, block in enumerate(self.json_blocks):
            try:
                json.loads(block)
            except json.JSONDecodeError as exc:
                self.fail(f"JSON block {i} failed to parse: {exc}\n{block}")

    def test_stale_task_example_has_required_fields(self) -> None:
        for block in self.json_blocks:
            obj = json.loads(block)
            if obj.get("kind") == "stale_task":
                for field in REQUIRED_FIELDS["stale_task"]:
                    self.assertIn(
                        field, obj,
                        f"stale_task example missing field: {field}",
                    )
                return
        self.fail("no stale_task JSON example found in doc")

    def test_state_corruption_example_has_required_fields(self) -> None:
        for block in self.json_blocks:
            obj = json.loads(block)
            if obj.get("kind") == "state_corruption_detected":
                for field in REQUIRED_FIELDS["state_corruption_detected"]:
                    self.assertIn(
                        field, obj,
                        f"state_corruption_detected example missing field: {field}",
                    )
                return
        self.fail("no state_corruption_detected JSON example found in doc")

    def test_stale_task_field_types(self) -> None:
        for block in self.json_blocks:
            obj = json.loads(block)
            if obj.get("kind") == "stale_task":
                self.assertIsInstance(obj["age_seconds"], int)
                self.assertIsInstance(obj["timeout_seconds"], int)
                self.assertIsInstance(obj["task_id"], str)
                self.assertIsInstance(obj["timestamp"], str)
                return

    def test_kind_field_matches_documented_values(self) -> None:
        documented_kinds = set(REQUIRED_FIELDS.keys())
        for block in self.json_blocks:
            obj = json.loads(block)
            kind = obj.get("kind")
            if kind is not None:
                self.assertIn(
                    kind, documented_kinds,
                    f"example uses undocumented kind: {kind}",
                )


if __name__ == "__main__":
    unittest.main()
