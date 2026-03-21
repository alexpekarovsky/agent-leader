"""Tests for orchestrator.pr_summary – PR description generation."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from orchestrator.pr_summary import generate_pr_summary


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

SAMPLE_TASK = {
    "id": "TASK-abcd1234",
    "title": "Add user authentication endpoint",
    "acceptance_criteria": [
        "POST /auth/login returns JWT token",
        "Invalid credentials return 401",
        "Test covers happy and error paths",
    ],
    "tags": ["backend", "auth"],
    "delivery_profile": {
        "risk": "medium",
        "test_plan": "targeted",
        "doc_impact": "none",
    },
}

SAMPLE_REPORT = {
    "task_id": "TASK-abcd1234",
    "agent": "claude_code",
    "commit_sha": "a1b2c3d4e5f6",
    "status": "done",
    "test_summary": {
        "command": ".venv/bin/python -m pytest tests/ -v",
        "passed": 42,
        "failed": 0,
    },
    "artifacts": ["src/auth.py", "tests/test_auth.py"],
    "notes": "Implemented JWT-based login with bcrypt password hashing.",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_generate_pr_summary_full():
    """Full task+report produces all expected markdown sections."""
    md = generate_pr_summary(task=SAMPLE_TASK, report=SAMPLE_REPORT)

    assert "## Summary" in md
    assert "`TASK-abcd1234`" in md
    assert "Add user authentication endpoint" in md

    assert "## Acceptance criteria" in md
    assert "- [ ] POST /auth/login returns JWT token" in md
    assert "- [ ] Invalid credentials return 401" in md

    assert "## Implementation notes" in md
    assert "JWT-based login" in md

    assert "## Test summary" in md
    assert "| 42 | 0 | 42 |" in md
    assert ".venv/bin/python -m pytest tests/ -v" in md

    assert "## Commit" in md
    assert "`a1b2c3d4e5f6`" in md

    assert "## Changed files" in md
    assert "- `src/auth.py`" in md
    assert "- `tests/test_auth.py`" in md

    assert "## Delivery profile" in md
    assert "**Risk:** medium" in md
    assert "**Test plan:** targeted" in md


def test_generate_pr_summary_minimal():
    """Minimal inputs still produce valid markdown."""
    md = generate_pr_summary(
        task={"title": "Quick fix"},
        report={"commit_sha": "deadbeef", "status": "done"},
    )

    assert "## Summary" in md
    assert "Quick fix" in md
    assert "`deadbeef`" in md
    # No acceptance criteria or notes sections
    assert "## Acceptance criteria" not in md
    assert "## Implementation notes" not in md
    assert "## Changed files" not in md


def test_changed_files_override():
    """Explicit changed_files overrides report artifacts."""
    md = generate_pr_summary(
        task=SAMPLE_TASK,
        report=SAMPLE_REPORT,
        changed_files=["README.md", "docs/api.md"],
    )

    assert "- `README.md`" in md
    assert "- `docs/api.md`" in md
    # Original artifacts should NOT appear
    assert "src/auth.py" not in md


def test_empty_artifacts_no_section():
    """Empty artifacts list omits the changed files section."""
    report = {**SAMPLE_REPORT, "artifacts": []}
    md = generate_pr_summary(task=SAMPLE_TASK, report=report, changed_files=[])

    assert "## Changed files" not in md


def test_test_summary_with_failures():
    """Failed tests are reflected in the table."""
    report = {
        **SAMPLE_REPORT,
        "test_summary": {
            "command": "pytest",
            "passed": 10,
            "failed": 3,
        },
    }
    md = generate_pr_summary(task=SAMPLE_TASK, report=report)

    assert "| 10 | 3 | 13 |" in md


def test_no_delivery_profile():
    """Missing delivery_profile omits that section."""
    task = {"title": "Bare task", "id": "TASK-0000"}
    md = generate_pr_summary(task=task, report=SAMPLE_REPORT)

    assert "## Delivery profile" not in md


def test_output_ends_with_newline():
    """Markdown output always ends with a single newline."""
    md = generate_pr_summary(task=SAMPLE_TASK, report=SAMPLE_REPORT)
    assert md.endswith("\n")
    assert not md.endswith("\n\n")
