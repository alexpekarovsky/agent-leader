from __future__ import annotations

import unittest
from pathlib import Path

from orchestrator.doctor import build_doctor_payload


class OrchestratorDoctorPayloadTests(unittest.TestCase):
    def test_healthy_payload_structure_and_status(self) -> None:
        payload = build_doctor_payload(
            root_dir=Path(".").resolve(),
            policy_path=Path("config/policy.codex-manager.json").resolve(),
            policy_name="policy.codex-manager.json",
            policy_loaded=True,
            binding_error=None,
            server_binding={
                "ok": True,
                "warnings": [],
                "startup_cwd_matches_root": True,
            },
            runtime_source_consistency={
                "ok": True,
                "warnings": [],
                "mismatch_detected": False,
            },
            manager="codex",
            roles={"leader": "codex", "team_members": ["claude_code", "gemini"]},
            agents=[
                {
                    "agent": "claude_code",
                    "status": "active",
                    "verified": True,
                    "same_project": True,
                    "reason": "verified_identity",
                }
            ],
            discovered={
                "registered_count": 1,
                "inferred_only_count": 0,
                "agents": [],
            },
            orch_available=True,
        )

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["degraded_mode"])
        self.assertIn("checks", payload)
        self.assertIn("summary", payload)
        self.assertIn("hints", payload)
        self.assertEqual(5, payload["summary"]["checks_total"])
        self.assertEqual(5, payload["summary"]["checks_passed"])
        self.assertTrue(payload["checks"]["root"]["ok"])
        self.assertTrue(payload["checks"]["policy"]["ok"])
        self.assertTrue(payload["checks"]["auth"]["ok"])
        self.assertTrue(payload["checks"]["connectivity"]["ok"])
        self.assertTrue(payload["checks"]["source_consistency"]["ok"])

    def test_degraded_payload_includes_actionable_hints(self) -> None:
        payload = build_doctor_payload(
            root_dir=Path("/nonexistent/root"),
            policy_path=Path("/nonexistent/policy.json"),
            policy_name="policy.json",
            policy_loaded=False,
            binding_error="ORCHESTRATOR_ROOT mismatch",
            server_binding={
                "ok": False,
                "warnings": [
                    "shared_install_without_orchestrator_root_env",
                    "shared_install_without_expected_root_env",
                ],
                "startup_cwd_matches_root": False,
            },
            runtime_source_consistency={
                "ok": False,
                "warnings": [
                    "source_hash_mismatch: runtime server may be stale",
                    "git_commit_mismatch: startup=abc1234 current=def5678",
                ],
                "mismatch_detected": True,
            },
            manager=None,
            roles={"leader": None, "team_members": []},
            agents=[
                {
                    "agent": "claude_code",
                    "status": "offline",
                    "verified": False,
                    "same_project": False,
                    "reason": "missing_identity_fields:client,model",
                },
                {
                    "agent": "gemini",
                    "status": "offline",
                    "verified": False,
                    "same_project": False,
                    "reason": "project_mismatch",
                },
            ],
            discovered={
                "registered_count": 2,
                "inferred_only_count": 1,
                "agents": [{"agent": "unregistered-worker"}],
            },
            orch_available=False,
        )

        self.assertFalse(payload["ok"])
        self.assertTrue(payload["degraded_mode"])
        self.assertFalse(payload["checks"]["root"]["ok"])
        self.assertFalse(payload["checks"]["policy"]["ok"])
        self.assertFalse(payload["checks"]["auth"]["ok"])
        self.assertFalse(payload["checks"]["connectivity"]["ok"])
        self.assertFalse(payload["checks"]["source_consistency"]["ok"])

        hints_text = "\n".join(payload["hints"])
        self.assertIn("ORCHESTRATOR_ROOT", hints_text)
        self.assertIn("ORCHESTRATOR_EXPECTED_ROOT", hints_text)
        self.assertIn("ORCHESTRATOR_POLICY", hints_text)
        self.assertIn("connect_to_leader", hints_text)
        self.assertIn("restart MCP server", hints_text)


if __name__ == "__main__":
    unittest.main()
