"""Dispatch telemetry noop diagnostic payload schema test stubs.

Documents expected noop event schema including reason codes, timeout
metadata fields, and task/agent correlation requirements. These stubs
validate the schema contract that CORE-06 implementation must satisfy.
"""

from __future__ import annotations

import unittest


# --- Schema definitions (contract for CORE-06 implementation) ---

NOOP_REASON_CODES = frozenset({
    "ack_timeout",          # Worker not running or didn't respond in time
    "no_available_worker",  # No agents registered for the target workstream
    "result_timeout",       # Worker acked but crashed before delivering result
})

NOOP_REQUIRED_FIELDS = {
    "type": str,            # Must be "dispatch.noop"
    "correlation_id": str,  # Links back to originating dispatch.command
    "reason": str,          # One of NOOP_REASON_CODES
    "task_id": str,         # Task that dispatch was attempted for
    "target_agent": str,    # Agent the dispatch was targeting
    "elapsed_seconds": (int, float),  # Time between command and noop
}

NOOP_OPTIONAL_FIELDS = {
    "dispatch_timeout_seconds": (int, float),  # Configured timeout threshold
    "source": str,                              # Emitting agent (usually manager)
    "timestamp": str,                           # ISO-8601 event timestamp
}

COMMAND_REQUIRED_FIELDS = {
    "type": str,            # Must be "dispatch.command"
    "correlation_id": str,  # UUID linking command→ack→result or command→noop
    "task_id": str,
    "target_agent": str,
    "timeout_seconds": (int, float),
}

ACK_REQUIRED_FIELDS = {
    "type": str,            # Must be "dispatch.ack"
    "correlation_id": str,  # Must match command
    "task_id": str,
    "source": str,          # Worker agent that acked
    "status": str,          # "accepted" or "rejected"
}

RESULT_REQUIRED_FIELDS = {
    "type": str,            # Must be "worker.result"
    "correlation_id": str,  # Must match command and ack
    "task_id": str,
    "source": str,          # Worker that produced result
    "outcome": str,         # "success" or "failure"
    "duration_seconds": (int, float),
}


class NoopReasonCodeTests(unittest.TestCase):
    """Validate noop reason code definitions."""

    def test_reason_codes_are_defined(self) -> None:
        self.assertEqual(len(NOOP_REASON_CODES), 3)

    def test_ack_timeout_in_codes(self) -> None:
        self.assertIn("ack_timeout", NOOP_REASON_CODES)

    def test_no_available_worker_in_codes(self) -> None:
        self.assertIn("no_available_worker", NOOP_REASON_CODES)

    def test_result_timeout_in_codes(self) -> None:
        self.assertIn("result_timeout", NOOP_REASON_CODES)

    def test_reason_codes_are_lowercase_snake_case(self) -> None:
        for code in NOOP_REASON_CODES:
            self.assertRegex(code, r"^[a-z][a-z0-9_]*$", f"bad format: {code}")

    def test_reason_codes_are_distinct(self) -> None:
        self.assertEqual(len(NOOP_REASON_CODES), len(set(NOOP_REASON_CODES)))


class NoopPayloadSchemaTests(unittest.TestCase):
    """Validate noop event required/optional field contracts."""

    def test_noop_has_correlation_id(self) -> None:
        self.assertIn("correlation_id", NOOP_REQUIRED_FIELDS)
        self.assertEqual(NOOP_REQUIRED_FIELDS["correlation_id"], str)

    def test_noop_has_reason(self) -> None:
        self.assertIn("reason", NOOP_REQUIRED_FIELDS)

    def test_noop_has_task_id(self) -> None:
        self.assertIn("task_id", NOOP_REQUIRED_FIELDS)

    def test_noop_has_target_agent(self) -> None:
        self.assertIn("target_agent", NOOP_REQUIRED_FIELDS)

    def test_noop_has_elapsed_seconds(self) -> None:
        self.assertIn("elapsed_seconds", NOOP_REQUIRED_FIELDS)

    def test_noop_type_is_dispatch_noop(self) -> None:
        self.assertIn("type", NOOP_REQUIRED_FIELDS)

    def test_noop_optional_has_timeout_config(self) -> None:
        self.assertIn("dispatch_timeout_seconds", NOOP_OPTIONAL_FIELDS)

    def test_noop_optional_has_source(self) -> None:
        self.assertIn("source", NOOP_OPTIONAL_FIELDS)


class NoopTimeoutMetadataTests(unittest.TestCase):
    """Timeout metadata field specifications."""

    def test_elapsed_seconds_is_numeric(self) -> None:
        allowed = NOOP_REQUIRED_FIELDS["elapsed_seconds"]
        self.assertIn(int, allowed if isinstance(allowed, tuple) else (allowed,))

    def test_dispatch_timeout_seconds_is_numeric(self) -> None:
        allowed = NOOP_OPTIONAL_FIELDS["dispatch_timeout_seconds"]
        self.assertIn(int, allowed if isinstance(allowed, tuple) else (allowed,))

    def test_sample_noop_validates(self) -> None:
        """A well-formed noop payload should satisfy all required fields."""
        sample = {
            "type": "dispatch.noop",
            "correlation_id": "corr-abc123",
            "reason": "ack_timeout",
            "task_id": "TASK-def456",
            "target_agent": "claude_code",
            "elapsed_seconds": 31,
        }
        for field, expected_type in NOOP_REQUIRED_FIELDS.items():
            self.assertIn(field, sample, f"missing {field}")
            if isinstance(expected_type, tuple):
                self.assertIsInstance(sample[field], expected_type)
            else:
                self.assertIsInstance(sample[field], expected_type)

    def test_sample_noop_reason_is_valid(self) -> None:
        sample_reason = "ack_timeout"
        self.assertIn(sample_reason, NOOP_REASON_CODES)


class CorrelationKeyTests(unittest.TestCase):
    """Task and agent correlation key assertions across dispatch events."""

    def test_command_has_correlation_id(self) -> None:
        self.assertIn("correlation_id", COMMAND_REQUIRED_FIELDS)

    def test_ack_has_correlation_id(self) -> None:
        self.assertIn("correlation_id", ACK_REQUIRED_FIELDS)

    def test_result_has_correlation_id(self) -> None:
        self.assertIn("correlation_id", RESULT_REQUIRED_FIELDS)

    def test_noop_has_correlation_id(self) -> None:
        self.assertIn("correlation_id", NOOP_REQUIRED_FIELDS)

    def test_all_events_have_task_id(self) -> None:
        for schema_name, schema in [
            ("command", COMMAND_REQUIRED_FIELDS),
            ("ack", ACK_REQUIRED_FIELDS),
            ("result", RESULT_REQUIRED_FIELDS),
            ("noop", NOOP_REQUIRED_FIELDS),
        ]:
            self.assertIn("task_id", schema, f"{schema_name} missing task_id")

    def test_correlation_chain_command_to_noop(self) -> None:
        """Noop correlation_id must match originating command."""
        command = {"correlation_id": "corr-xyz", "task_id": "TASK-1"}
        noop = {"correlation_id": "corr-xyz", "task_id": "TASK-1"}
        self.assertEqual(command["correlation_id"], noop["correlation_id"])
        self.assertEqual(command["task_id"], noop["task_id"])

    def test_correlation_chain_full_lifecycle(self) -> None:
        """Full chain: command → ack → result all share correlation_id."""
        cid = "corr-lifecycle"
        command = {"correlation_id": cid, "task_id": "TASK-2"}
        ack = {"correlation_id": cid, "task_id": "TASK-2"}
        result = {"correlation_id": cid, "task_id": "TASK-2"}
        self.assertEqual(command["correlation_id"], ack["correlation_id"])
        self.assertEqual(ack["correlation_id"], result["correlation_id"])


if __name__ == "__main__":
    unittest.main()
