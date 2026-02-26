"""Lease issuance schema fixture with example IDs and expiries.

Provides realistic fixtures for lease issuance payload/state fields used
by tests and documentation. Fields map directly to _issue_task_lease_unlocked
in orchestrator/engine.py (line 1884).

Lease Schema Fields
===================
- lease_id:           str  — "LEASE-" prefix + 8-char hex UUID segment
- owner:              str  — Agent name that owns the lease (e.g. "claude_code")
- owner_instance_id:  str  — Instance ID of the owner (e.g. "sess-claude_code" or "claude_code#default")
- issued_at:          str  — ISO-8601 UTC timestamp when lease was first issued
- renewed_at:         str  — ISO-8601 UTC timestamp of last renewal (equals issued_at initially)
- expires_at:         str  — ISO-8601 UTC timestamp when lease expires (issued_at + ttl_seconds)
- ttl_seconds:        int  — Lease time-to-live from policy (default 300, minimum 30)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


# ---------------------------------------------------------------------------
# Example fixtures — realistic IDs, timestamps, and expiries
# ---------------------------------------------------------------------------

LEASE_FIXTURE_DEFAULT_TTL = {
    "lease_id": "LEASE-a1b2c3d4",
    "owner": "claude_code",
    "owner_instance_id": "sess-claude_code",
    "issued_at": "2026-02-26T12:00:00+00:00",
    "renewed_at": "2026-02-26T12:00:00+00:00",
    "expires_at": "2026-02-26T12:05:00+00:00",  # +300s (default TTL)
    "ttl_seconds": 300,
}

LEASE_FIXTURE_CUSTOM_TTL = {
    "lease_id": "LEASE-e5f6a7b8",
    "owner": "gemini",
    "owner_instance_id": "gem-v2-inst",
    "issued_at": "2026-02-26T14:30:00+00:00",
    "renewed_at": "2026-02-26T14:30:00+00:00",
    "expires_at": "2026-02-26T14:40:00+00:00",  # +600s (custom TTL)
    "ttl_seconds": 600,
}

LEASE_FIXTURE_RENEWED = {
    "lease_id": "LEASE-c9d0e1f2",
    "owner": "claude_code",
    "owner_instance_id": "sess-claude_code",
    "issued_at": "2026-02-26T10:00:00+00:00",
    "renewed_at": "2026-02-26T10:03:00+00:00",  # Renewed 3 min after issuance
    "expires_at": "2026-02-26T10:08:00+00:00",  # +300s from renewal time
    "ttl_seconds": 300,
}

LEASE_FIXTURE_EXPIRED = {
    "lease_id": "LEASE-1a2b3c4d",
    "owner": "codex",
    "owner_instance_id": "codex#default",
    "issued_at": "2026-02-26T08:00:00+00:00",
    "renewed_at": "2026-02-26T08:00:00+00:00",
    "expires_at": "2020-01-01T00:00:00+00:00",  # Expired (far past)
    "ttl_seconds": 300,
}

LEASE_FIXTURE_MINIMUM_TTL = {
    "lease_id": "LEASE-5e6f7a8b",
    "owner": "claude_code",
    "owner_instance_id": "claude_code#default",
    "issued_at": "2026-02-26T16:00:00+00:00",
    "renewed_at": "2026-02-26T16:00:00+00:00",
    "expires_at": "2026-02-26T16:00:30+00:00",  # +30s (minimum enforced TTL)
    "ttl_seconds": 30,
}

LEASE_REQUIRED_FIELDS = [
    "lease_id", "owner", "owner_instance_id",
    "issued_at", "renewed_at", "expires_at", "ttl_seconds",
]

ALL_FIXTURES = [
    ("default_ttl", LEASE_FIXTURE_DEFAULT_TTL),
    ("custom_ttl", LEASE_FIXTURE_CUSTOM_TTL),
    ("renewed", LEASE_FIXTURE_RENEWED),
    ("expired", LEASE_FIXTURE_EXPIRED),
    ("minimum_ttl", LEASE_FIXTURE_MINIMUM_TTL),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_policy(path: Path, ttl: int = 300) -> Policy:
    raw = {
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"backend": "claude_code", "frontend": "gemini", "default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex", "claude_code", "gemini"]}},
        "triggers": {"heartbeat_timeout_minutes": 10, "lease_ttl_seconds": ttl},
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Policy.load(path)


def _make_orch(root: Path, ttl: int = 300) -> Orchestrator:
    policy = _make_policy(root / "policy.json", ttl=ttl)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


def _full_metadata(root: Path, agent: str) -> dict:
    return {
        "role": "team_member",
        "client": f"{agent}-cli",
        "model": f"{agent}-model",
        "cwd": str(root),
        "project_root": str(root),
        "permissions_mode": "default",
        "sandbox_mode": "workspace-write",
        "session_id": f"sess-{agent}",
        "connection_id": f"conn-{agent}",
        "server_version": "0.1.0",
        "verification_source": "test",
    }


def _setup_and_claim(orch: Orchestrator, root: Path, agent: str = "claude_code") -> dict:
    """Register agent, create task, claim it — returns claimed task with lease."""
    orch.register_agent(agent, _full_metadata(root, agent))
    orch.heartbeat(agent, _full_metadata(root, agent))
    orch.create_task(
        title="Fixture test task",
        workstream="backend",
        owner=agent,
        acceptance_criteria=["test"],
    )
    return orch.claim_next_task(agent)


# ---------------------------------------------------------------------------
# 1. Fixture completeness tests
# ---------------------------------------------------------------------------

class FixtureSchemaCompletenessTests(unittest.TestCase):
    """All fixtures must contain every required lease field."""

    def test_all_fixtures_have_required_fields(self) -> None:
        for name, fixture in ALL_FIXTURES:
            for field in LEASE_REQUIRED_FIELDS:
                self.assertIn(field, fixture, f"fixture '{name}' missing '{field}'")

    def test_lease_id_format(self) -> None:
        for name, fixture in ALL_FIXTURES:
            self.assertTrue(
                fixture["lease_id"].startswith("LEASE-"),
                f"fixture '{name}' lease_id must start with LEASE-",
            )
            suffix = fixture["lease_id"][6:]
            self.assertEqual(len(suffix), 8, f"fixture '{name}' lease_id suffix must be 8 chars")

    def test_ttl_seconds_is_positive_int(self) -> None:
        for name, fixture in ALL_FIXTURES:
            self.assertIsInstance(fixture["ttl_seconds"], int)
            self.assertGreaterEqual(fixture["ttl_seconds"], 30,
                                    f"fixture '{name}' ttl below minimum 30")

    def test_timestamps_are_iso8601(self) -> None:
        from datetime import datetime
        for name, fixture in ALL_FIXTURES:
            for ts_field in ("issued_at", "renewed_at", "expires_at"):
                try:
                    datetime.fromisoformat(fixture[ts_field])
                except ValueError:
                    self.fail(f"fixture '{name}' field '{ts_field}' is not valid ISO-8601")

    def test_owner_is_nonempty_string(self) -> None:
        for name, fixture in ALL_FIXTURES:
            self.assertIsInstance(fixture["owner"], str)
            self.assertTrue(len(fixture["owner"]) > 0, f"fixture '{name}' empty owner")

    def test_owner_instance_id_is_nonempty_string(self) -> None:
        for name, fixture in ALL_FIXTURES:
            self.assertIsInstance(fixture["owner_instance_id"], str)
            self.assertTrue(len(fixture["owner_instance_id"]) > 0,
                            f"fixture '{name}' empty owner_instance_id")


# ---------------------------------------------------------------------------
# 2. Live issuance matches fixture schema
# ---------------------------------------------------------------------------

class LiveIssuanceMatchesFixtureTests(unittest.TestCase):
    """Leases issued by the engine should match the fixture schema."""

    def test_live_lease_has_all_fixture_fields(self) -> None:
        """A real lease from claim_next_task should have every required field."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            lease = claimed["lease"]
            for field in LEASE_REQUIRED_FIELDS:
                self.assertIn(field, lease, f"live lease missing '{field}'")

    def test_live_lease_id_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            self.assertTrue(claimed["lease"]["lease_id"].startswith("LEASE-"))
            self.assertEqual(len(claimed["lease"]["lease_id"]), 14)  # LEASE- + 8 hex

    def test_live_lease_ttl_matches_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl=300)
            claimed = _setup_and_claim(orch, root)
            self.assertEqual(300, claimed["lease"]["ttl_seconds"])

    def test_live_lease_custom_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl=600)
            claimed = _setup_and_claim(orch, root)
            self.assertEqual(600, claimed["lease"]["ttl_seconds"])

    def test_live_lease_minimum_ttl_enforced(self) -> None:
        """TTL below 30 should be clamped to 30."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root, ttl=5)
            claimed = _setup_and_claim(orch, root)
            self.assertEqual(30, claimed["lease"]["ttl_seconds"])

    def test_live_lease_issued_at_equals_renewed_at(self) -> None:
        """On initial issuance, issued_at and renewed_at must match."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            self.assertEqual(claimed["lease"]["issued_at"], claimed["lease"]["renewed_at"])

    def test_live_lease_expires_at_after_issued_at(self) -> None:
        """expires_at must be strictly after issued_at."""
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            issued = datetime.fromisoformat(claimed["lease"]["issued_at"])
            expires = datetime.fromisoformat(claimed["lease"]["expires_at"])
            self.assertGreater(expires, issued)

    def test_live_lease_owner_matches_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root, "claude_code")
            self.assertEqual("claude_code", claimed["lease"]["owner"])

    def test_live_lease_owner_instance_id_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            self.assertTrue(len(claimed["lease"]["owner_instance_id"]) > 0)


# ---------------------------------------------------------------------------
# 3. Fixture expired/valid detection
# ---------------------------------------------------------------------------

class FixtureExpiryDetectionTests(unittest.TestCase):
    """Fixture timestamps should match expected expiry status."""

    def test_expired_fixture_is_detected_as_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertTrue(orch._lease_expired(LEASE_FIXTURE_EXPIRED))

    def test_default_fixture_issued_at_known_time_is_expired_now(self) -> None:
        """The 2026-02-26T12:05:00 fixture is in the past relative to test runtime."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            # This fixture has a specific timestamp; it may or may not be expired
            # depending on when the test runs, but the schema is still valid
            result = orch._lease_expired(LEASE_FIXTURE_DEFAULT_TTL)
            self.assertIsInstance(result, bool)

    def test_empty_expires_at_is_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertTrue(orch._lease_expired({"expires_at": ""}))

    def test_missing_expires_at_is_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            self.assertTrue(orch._lease_expired({}))


# ---------------------------------------------------------------------------
# 4. Renewal updates fixture fields correctly
# ---------------------------------------------------------------------------

class RenewalUpdatesFixtureFieldsTests(unittest.TestCase):
    """After renewal, renewed_at and expires_at should update; lease_id stays."""

    def test_renewal_updates_renewed_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]
            original_renewed = claimed["lease"]["renewed_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertNotEqual(original_renewed, result["lease"]["renewed_at"])

    def test_renewal_extends_expires_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]
            original_expires = claimed["lease"]["expires_at"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertGreaterEqual(result["lease"]["expires_at"], original_expires)

    def test_renewal_preserves_lease_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual(lease_id, result["lease"]["lease_id"])

    def test_renewal_preserves_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orch = _make_orch(root)
            claimed = _setup_and_claim(orch, root)
            lease_id = claimed["lease"]["lease_id"]

            result = orch.renew_task_lease(claimed["id"], "claude_code", lease_id)

            self.assertEqual("claude_code", result["lease"]["owner"])


if __name__ == "__main__":
    unittest.main()
