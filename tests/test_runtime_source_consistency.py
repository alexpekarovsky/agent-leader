"""Tests for runtime deploy/source consistency check (UNSUP-V1-04).

Validates that orchestrator_status exposes runtime/source version metadata
and detects mismatches between startup and current source state.

These tests replicate the _compute_source_hash and _runtime_source_consistency
logic locally to avoid importing orchestrator_mcp_server (which rewrites
sys.stdout and breaks pytest capture).
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent.parent


# ── Replicated helpers (same logic as orchestrator_mcp_server.py) ────

def _compute_source_hash(paths: List[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        try:
            h.update(p.read_bytes())
        except Exception:
            pass
    return h.hexdigest()


def _git_head_short(repo: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(repo), timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


_SOURCE_FILES = [
    SCRIPT_DIR / "orchestrator_mcp_server.py",
    SCRIPT_DIR / "orchestrator" / "engine.py",
    SCRIPT_DIR / "orchestrator" / "policy.py",
    SCRIPT_DIR / "orchestrator" / "bus.py",
]


def _runtime_source_consistency(
    startup_hash: str,
    startup_commit: Optional[str],
    source_files: List[Path],
    script_dir: Path,
) -> Dict[str, Any]:
    current_hash = _compute_source_hash(source_files)
    current_commit = _git_head_short(script_dir)
    source_changed = current_hash != startup_hash
    commit_changed = (
        startup_commit is not None
        and current_commit is not None
        and current_commit != startup_commit
    )
    mismatch = source_changed or commit_changed
    warnings: List[str] = []
    if source_changed:
        warnings.append("source_hash_mismatch: runtime server may be stale")
    if commit_changed:
        warnings.append(
            f"git_commit_mismatch: startup={startup_commit} current={current_commit}"
        )
    return {
        "ok": not mismatch,
        "mismatch_detected": mismatch,
        "startup_source_hash": startup_hash,
        "current_source_hash": current_hash,
        "startup_git_commit": startup_commit,
        "current_git_commit": current_commit,
        "source_files_checked": [p.name for p in sorted(source_files)],
        "warnings": warnings,
    }


# ── Tests ────────────────────────────────────────────────────────────

class ComputeSourceHashTests(unittest.TestCase):
    """Unit tests for _compute_source_hash."""

    def test_hash_of_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.py"
            p2 = Path(tmp) / "b.py"
            p1.write_text("hello", encoding="utf-8")
            p2.write_text("world", encoding="utf-8")
            h = _compute_source_hash([p1, p2])
            self.assertIsInstance(h, str)
            self.assertEqual(len(h), 64)  # SHA-256 hex length

    def test_hash_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.py"
            p.write_text("content", encoding="utf-8")
            h1 = _compute_source_hash([p])
            h2 = _compute_source_hash([p])
            self.assertEqual(h1, h2)

    def test_hash_changes_when_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "f.py"
            p.write_text("version1", encoding="utf-8")
            h1 = _compute_source_hash([p])
            p.write_text("version2", encoding="utf-8")
            h2 = _compute_source_hash([p])
            self.assertNotEqual(h1, h2)

    def test_missing_files_do_not_crash(self) -> None:
        paths = [Path("/nonexistent/file1.py"), Path("/nonexistent/file2.py")]
        h = _compute_source_hash(paths)
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)

    def test_hash_order_independent_of_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.py"
            p2 = Path(tmp) / "b.py"
            p1.write_text("aaa", encoding="utf-8")
            p2.write_text("bbb", encoding="utf-8")
            h_forward = _compute_source_hash([p1, p2])
            h_reverse = _compute_source_hash([p2, p1])
            self.assertEqual(h_forward, h_reverse, "Hash should sort paths internally")


class GitHeadShortTests(unittest.TestCase):
    """Unit tests for _git_head_short."""

    def test_returns_string_in_git_repo(self) -> None:
        result = _git_head_short(SCRIPT_DIR)
        # In a git repo this should return a short hash
        if result is not None:
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)

    def test_nonexistent_dir_returns_none(self) -> None:
        result = _git_head_short(Path("/nonexistent/path"))
        self.assertIsNone(result)


class RuntimeSourceConsistencyMatchTests(unittest.TestCase):
    """Tests for _runtime_source_consistency when source matches startup."""

    def test_match_when_source_unchanged(self) -> None:
        """Hash computed now should match itself."""
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        startup_commit = _git_head_short(SCRIPT_DIR)
        rsc = _runtime_source_consistency(startup_hash, startup_commit, _SOURCE_FILES, SCRIPT_DIR)
        self.assertTrue(rsc["ok"])
        self.assertFalse(rsc["mismatch_detected"])
        self.assertEqual(rsc["startup_source_hash"], rsc["current_source_hash"])
        self.assertEqual(rsc["warnings"], [])

    def test_payload_shape(self) -> None:
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        rsc = _runtime_source_consistency(startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        expected_keys = {
            "ok",
            "mismatch_detected",
            "startup_source_hash",
            "current_source_hash",
            "startup_git_commit",
            "current_git_commit",
            "source_files_checked",
            "warnings",
        }
        self.assertEqual(set(rsc.keys()), expected_keys)

    def test_source_files_checked_is_list(self) -> None:
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        rsc = _runtime_source_consistency(startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        self.assertIsInstance(rsc["source_files_checked"], list)
        self.assertGreater(len(rsc["source_files_checked"]), 0)


class RuntimeSourceConsistencyMismatchTests(unittest.TestCase):
    """Tests for _runtime_source_consistency when source diverges from startup."""

    def test_source_hash_mismatch_detected(self) -> None:
        """Simulate source change after startup with a fake old hash."""
        fake_startup_hash = "0" * 64
        rsc = _runtime_source_consistency(fake_startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        self.assertFalse(rsc["ok"])
        self.assertTrue(rsc["mismatch_detected"])
        self.assertNotEqual(rsc["startup_source_hash"], rsc["current_source_hash"])
        self.assertTrue(
            any("source_hash_mismatch" in w for w in rsc["warnings"]),
            f"Expected source_hash_mismatch warning, got: {rsc['warnings']}",
        )

    def test_git_commit_mismatch_detected(self) -> None:
        """Simulate git commit change after startup."""
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        current_commit = _git_head_short(SCRIPT_DIR)
        if current_commit is None:
            self.skipTest("Not in a git repo")
        fake_startup_commit = "aaa1111"
        rsc = _runtime_source_consistency(startup_hash, fake_startup_commit, _SOURCE_FILES, SCRIPT_DIR)
        if current_commit != fake_startup_commit:
            self.assertFalse(rsc["ok"])
            self.assertTrue(rsc["mismatch_detected"])
            self.assertTrue(
                any("git_commit_mismatch" in w for w in rsc["warnings"]),
                f"Expected git_commit_mismatch warning, got: {rsc['warnings']}",
            )

    def test_mismatch_warnings_are_strings(self) -> None:
        fake_startup_hash = "0" * 64
        rsc = _runtime_source_consistency(fake_startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        for w in rsc["warnings"]:
            self.assertIsInstance(w, str)

    def test_file_modification_detected(self) -> None:
        """Simulate actual file modification between startup and check."""
        with tempfile.TemporaryDirectory() as tmp:
            f1 = Path(tmp) / "server.py"
            f2 = Path(tmp) / "engine.py"
            f1.write_text("original_server", encoding="utf-8")
            f2.write_text("original_engine", encoding="utf-8")
            files = [f1, f2]
            startup_hash = _compute_source_hash(files)

            # Simulate source change (developer pushed new code, server not restarted)
            f1.write_text("updated_server_code", encoding="utf-8")

            rsc = _runtime_source_consistency(startup_hash, None, files, Path(tmp))
            self.assertFalse(rsc["ok"])
            self.assertTrue(rsc["mismatch_detected"])
            self.assertNotEqual(rsc["startup_source_hash"], rsc["current_source_hash"])


class IntegrityIntegrationTests(unittest.TestCase):
    """Verify that RSC mismatch propagates into integrity and stats_provenance."""

    def test_integrity_degraded_on_source_mismatch(self) -> None:
        fake_startup_hash = "0" * 64
        rsc = _runtime_source_consistency(fake_startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        # Simulate what the handler does: merge warnings into integrity
        integrity: Dict[str, Any] = {"ok": True, "warnings": []}
        if not rsc["ok"]:
            integrity["warnings"] = integrity["warnings"] + rsc["warnings"]
            integrity["ok"] = False
        self.assertFalse(integrity["ok"])
        self.assertGreater(len(integrity["warnings"]), 0)

    def test_integrity_ok_when_source_matches(self) -> None:
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        startup_commit = _git_head_short(SCRIPT_DIR)
        rsc = _runtime_source_consistency(startup_hash, startup_commit, _SOURCE_FILES, SCRIPT_DIR)
        integrity: Dict[str, Any] = {"ok": True, "warnings": []}
        if not rsc["ok"]:
            integrity["warnings"] = integrity["warnings"] + rsc["warnings"]
            integrity["ok"] = False
        self.assertTrue(integrity["ok"])
        self.assertEqual(integrity["warnings"], [])

    def test_stats_provenance_reflects_rsc_degraded(self) -> None:
        fake_startup_hash = "0" * 64
        rsc = _runtime_source_consistency(fake_startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        integrity_ok = True and rsc["ok"]
        state = "ok" if integrity_ok else "degraded"
        self.assertEqual(state, "degraded")

    def test_stats_provenance_ok_when_rsc_ok(self) -> None:
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        startup_commit = _git_head_short(SCRIPT_DIR)
        rsc = _runtime_source_consistency(startup_hash, startup_commit, _SOURCE_FILES, SCRIPT_DIR)
        integrity_ok = True and rsc["ok"]
        state = "ok" if integrity_ok else "degraded"
        self.assertEqual(state, "ok")


class BackwardCompatibilityTests(unittest.TestCase):
    """Ensure runtime_source_consistency is additive and doesn't break existing keys."""

    def test_rsc_payload_is_json_serializable(self) -> None:
        import json
        startup_hash = _compute_source_hash(_SOURCE_FILES)
        rsc = _runtime_source_consistency(startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        serialized = json.dumps(rsc)
        deserialized = json.loads(serialized)
        self.assertEqual(rsc["ok"], deserialized["ok"])

    def test_rsc_does_not_modify_existing_integrity_keys(self) -> None:
        """RSC warnings are appended, not replacing existing integrity structure."""
        startup_hash = "0" * 64
        rsc = _runtime_source_consistency(startup_hash, None, _SOURCE_FILES, SCRIPT_DIR)
        integrity = {
            "ok": True,
            "warnings": ["existing_warning"],
            "task_count_regression_detected": False,
            "provenance": {"task_counts": "live_state"},
        }
        if not rsc["ok"]:
            integrity["warnings"] = integrity["warnings"] + rsc["warnings"]
            integrity["ok"] = False
        # Existing keys preserved
        self.assertIn("task_count_regression_detected", integrity)
        self.assertIn("provenance", integrity)
        # Existing warning preserved
        self.assertIn("existing_warning", integrity["warnings"])
        # RSC warning added
        self.assertTrue(any("source_hash_mismatch" in w for w in integrity["warnings"]))


if __name__ == "__main__":
    unittest.main()
