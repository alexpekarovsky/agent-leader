"""Consolidated tests for GitHub CI normalization, webhook processing,
issue creation, handoff events, and MCP tool integration."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from orchestrator.github_ci import build_github_issue_payload, normalize_github_ci_result

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _find_available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _make_orchestrator(tmp):
    """Create a minimal Orchestrator in *tmp* for unit tests."""
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy

    root = Path(tmp)
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps({
        "name": "test-policy",
        "roles": {"manager": "codex"},
        "routing": {"default": "codex"},
        "decisions": {"architecture": {"mode": "consensus", "members": ["codex"]}},
        "triggers": {"heartbeat_timeout_minutes": 10},
    }))
    policy = Policy.load(policy_path)
    orch = Orchestrator(root=root, policy=policy)
    orch.bootstrap()
    return orch


@pytest.fixture
def github_token_set():
    os.environ["GITHUB_TOKEN"] = "test_github_token"
    yield
    os.environ.pop("GITHUB_TOKEN", None)


# ===================================================================
# 1. normalize_github_ci_result
# ===================================================================

class TestNormalization:
    @pytest.mark.parametrize("status,conclusion,expected_state", [
        ("completed", "success", "passed"),
        ("completed", "failure", "failed"),
        ("in_progress", None, "running"),
    ])
    def test_state_mapping(self, status, conclusion, expected_state):
        payload = {"name": "ci-check", "status": status, "conclusion": conclusion}
        assert normalize_github_ci_result(payload)["state"] == expected_state

    def test_success_preserves_counts(self):
        payload = {
            "name": "backend-tests", "status": "completed", "conclusion": "success",
            "head_sha": "abc123", "head_branch": "main",
            "html_url": "https://github.com/org/repo/actions/runs/1",
            "run_id": 1, "run_attempt": 2, "passed": 120, "failed": 0,
        }
        r = normalize_github_ci_result(payload)
        assert r["passed"] == 120
        assert r["failed"] == 0
        assert r["conclusion"] == "success"

    def test_failure_normalizes_aliases(self):
        payload = {
            "workflow": "frontend-ci", "status": "completed", "conclusion": "failure",
            "sha": "def456", "branch": "feature/x",
            "url": "https://example.test/ci/2", "id": "42", "attempt": "1",
        }
        r = normalize_github_ci_result(payload)
        assert r["name"] == "frontend-ci"
        assert r["run_id"] == 42
        assert r["attempt"] == 1

    def test_empty_payload_defaults(self):
        r = normalize_github_ci_result({})
        assert r["state"] == "unknown"
        assert r["name"] == "ci"
        assert r["run_id"] is None
        assert r["attempt"] is None


# ===================================================================
# 2. MCP tool: orchestrator_normalize_github_ci
# ===================================================================

class TestNormalizeMcpTool:
    def test_tools_list_contains_normalizer(self):
        from orchestrator_mcp_server import handle_tools_list
        names = {t["name"] for t in handle_tools_list("r")["result"]["tools"]}
        assert "orchestrator_normalize_github_ci" in names

    def test_dict_payload(self):
        from orchestrator_mcp_server import handle_tool_call
        resp = handle_tool_call("r", {
            "name": "orchestrator_normalize_github_ci",
            "arguments": {"payload": {
                "name": "backend-tests", "status": "completed",
                "conclusion": "success", "head_sha": "abc123",
            }},
        })
        p = json.loads(resp["result"]["content"][0]["text"])
        assert p["provider"] == "github"
        assert p["state"] == "passed"
        assert p["sha"] == "abc123"

    def test_json_string_payload(self):
        from orchestrator_mcp_server import handle_tool_call
        resp = handle_tool_call("r", {
            "name": "orchestrator_normalize_github_ci",
            "arguments": {"payload": '{"name":"lint","status":"in_progress","conclusion":null}'},
        })
        p = json.loads(resp["result"]["content"][0]["text"])
        assert p["state"] == "running"
        assert p["name"] == "lint"

    def test_rejects_non_object(self):
        from orchestrator_mcp_server import handle_tool_call
        resp = handle_tool_call("r", {
            "name": "orchestrator_normalize_github_ci",
            "arguments": {"payload": []},
        })
        assert "payload must be an object" in resp["error"]["message"]


# ===================================================================
# 3. MCP tool: orchestrator_process_github_webhook
# ===================================================================

class TestWebhookMcpTool:
    """Tests for handle_tool_call('orchestrator_process_github_webhook', ...)."""

    @staticmethod
    def _call(mock_orch, payload, *, event="check_run"):
        from orchestrator_mcp_server import handle_tool_call
        params = {
            "name": "orchestrator_process_github_webhook",
            "arguments": {"payload": payload, "source": "github",
                          "headers": {"X-GitHub-Event": event}},
        }
        return handle_tool_call("r", params)

    # -- check_run events (parametrized) --------------------------------

    @pytest.mark.parametrize("ci_state,conclusion,action", [
        ("passed",  "success", "completed"),
        ("failed",  "failure", "completed"),
        ("running", None,      "created"),
    ])
    @patch("orchestrator_mcp_server.ORCH")
    def test_check_run_ci_states(self, mock_orch, ci_state, conclusion, action):
        mock_orch.process_github_webhook.return_value = {
            "event_type": "check_run", "repo": "t/r",
            "status": "ci_updated", "ci_state": ci_state,
            "details": "ok", "updated_prs": [{
                "pr_id": "PR-0", "pr_number": 1,
                "stack_id": "STACK-m", "ci_state": ci_state,
            }],
        }
        payload = {
            "action": action,
            "check_run": {"id": 1, "external_id": "TASK-x",
                          "status": "completed" if conclusion else "in_progress",
                          "conclusion": conclusion, "output": {"text": ""}},
            "repository": {"full_name": "t/r"},
        }
        result = self._call(mock_orch, payload)
        parsed = json.loads(result["result"]["content"][0]["text"])
        assert parsed["ci_state"] == ci_state
        mock_orch.process_github_webhook.assert_called_once()

    @patch("orchestrator_mcp_server.ORCH")
    def test_check_run_no_matching_pr(self, mock_orch):
        mock_orch.process_github_webhook.return_value = {
            "event_type": "check_run", "repo": "t/r",
            "status": "ci_no_matching_pr_in_stack", "ci_state": "passed",
            "details": "no match",
        }
        payload = {
            "action": "completed",
            "check_run": {"id": 9, "status": "completed", "conclusion": "success",
                          "output": {"text": "ok"}},
            "repository": {"full_name": "t/r"},
        }
        parsed = json.loads(self._call(mock_orch, payload)["result"]["content"][0]["text"])
        assert parsed["status"] == "ci_no_matching_pr_in_stack"

    @patch("orchestrator_mcp_server.ORCH")
    def test_check_run_task_id_from_output_text(self, mock_orch):
        mock_orch.process_github_webhook.return_value = {
            "event_type": "check_run", "repo": "t/r",
            "status": "ci_updated", "ci_state": "passed", "details": "ok",
            "updated_prs": [{"pr_id": "PR-2", "pr_number": 3,
                             "stack_id": "STACK-m", "ci_state": "passed"}],
        }
        payload = {
            "action": "completed",
            "check_run": {"id": 5, "status": "completed", "conclusion": "success",
                          "output": {"text": "CI passed for TASK-aabbcc11 on main"}},
            "repository": {"full_name": "t/r"},
        }
        parsed = json.loads(self._call(mock_orch, payload)["result"]["content"][0]["text"])
        assert parsed["status"] == "ci_updated"

    # -- pull_request events (parametrized) -----------------------------

    @pytest.mark.parametrize("action,merged,expected_status", [
        ("opened", False, "pr_updated"),
        ("closed", True,  "pr_merged"),
        ("closed", False, "pr_closed"),
    ])
    @patch("orchestrator_mcp_server.ORCH")
    def test_pull_request_events(self, mock_orch, action, merged, expected_status):
        mock_orch.process_github_webhook.return_value = {
            "event_type": "pull_request", "repo": "t/r",
            "status": expected_status, "details": "ok",
            "pr_id": "PR-0", "pr_number": 1,
        }
        payload = {
            "action": action,
            "pull_request": {
                "number": 1, "head": {"ref": "fb", "sha": "aaa"},
                "base": {"ref": "main"}, "title": "PR",
                "state": "open" if action == "opened" else "closed",
                "merged": merged,
            },
            "repository": {"full_name": "t/r"},
            "sender": {"login": "u"},
        }
        parsed = json.loads(
            self._call(mock_orch, payload, event="pull_request")["result"]["content"][0]["text"])
        assert parsed["status"] == expected_status

    # -- error path -----------------------------------------------------

    def test_orch_not_initialized(self):
        from orchestrator_mcp_server import handle_tool_call
        with patch("orchestrator_mcp_server.ORCH", None):
            result = handle_tool_call("r", {
                "name": "orchestrator_process_github_webhook",
                "arguments": {"payload": {"repository": {"full_name": "t/r"}},
                              "source": "github"},
            })
        assert "not initialized" in result["error"]["message"].lower()


# ===================================================================
# 4. GitHub issue creation
# ===================================================================

class TestGitHubIssue:
    def test_build_payload_structure(self):
        bug = {
            "id": "BUG-aabbccdd", "source_task": "TASK-11223344",
            "owner": "claude_code", "severity": "critical",
            "repro_steps": "1. Run\n2. Crash", "expected": "OK",
            "actual": "RuntimeError", "status": "open",
        }
        p = build_github_issue_payload(bug)
        assert p["title"] == "[CRITICAL Bug] Task TASK-11223344: RuntimeError"
        assert "BUG-aabbccdd" in p["body"]
        assert "severity:critical" in p["labels"]
        assert "bug" in p["labels"]
        assert p["assignees"] == ["claude_code"]

    @pytest.mark.parametrize("severity", ["critical", "high", "medium", "low"])
    def test_severity_label_mapping(self, severity):
        bug = {
            "id": f"BUG-{severity[:8].ljust(8, '0')}",
            "source_task": "TASK-aabb0011", "owner": "codex",
            "severity": severity, "repro_steps": "r",
            "expected": "e", "actual": "a", "status": "open",
        }
        p = build_github_issue_payload(bug)
        assert f"[{severity.upper()} Bug]" in p["title"]
        assert f"severity:{severity}" in p["labels"]

    @patch("orchestrator_mcp_server.ORCH")
    def test_mcp_create_github_issue(self, mock_orch):
        from orchestrator_mcp_server import handle_tool_call
        mock_orch.orchestrator_create_github_issue.return_value = {
            "status": "success", "action": "github_issue_created",
            "bug_id": "BUG-12345678", "repo": "test/repo",
            "issue_number": 123,
            "issue_url": "https://github.com/test/repo/issues/123",
            "issue_title": "[HIGH Bug] Task TASK-abcdef12: Crashed on startup",
        }
        result = handle_tool_call("r", {
            "name": "orchestrator_create_github_issue",
            "arguments": {"bug_id": "BUG-12345678", "repo": "test/repo"},
        })
        parsed = json.loads(result["result"]["content"][0]["text"])
        assert parsed["status"] == "success"
        assert parsed["issue_number"] == 123

    def test_orchestrator_creates_issue_with_fake_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            bug = {
                "id": "BUG-aabbccdd", "source_task": "TASK-11223344",
                "owner": "claude_code", "severity": "critical",
                "repro_steps": "1. Run\n2. Crash", "expected": "OK",
                "actual": "RuntimeError on task creation", "status": "open",
                "created_at": "2026-03-21T00:00:00Z",
            }
            orch._write_json(orch.bugs_path, [bug])
            with patch.dict(os.environ, {"GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "fake"}):
                r = orch._create_github_issue_from_bug(bug, repo_full_name="o/r")
            assert r["status"] == "success"
            assert r["issue_title"] == "[CRITICAL Bug] Task TASK-11223344: RuntimeError on task creation"
            bugs = orch._read_json_list(orch.bugs_path)
            assert "github_issue" in next(b for b in bugs if b["id"] == "BUG-aabbccdd")

    def test_skips_without_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = _make_orchestrator(tmp)
            bug = {
                "id": "BUG-99887766", "source_task": "TASK-55667788",
                "owner": "gemini", "severity": "medium",
                "repro_steps": "s", "expected": "e", "actual": "a", "status": "open",
            }
            env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            env["GITHUB_REPOSITORY"] = "o/r"
            with patch.dict(os.environ, env, clear=True):
                r = orch._create_github_issue_from_bug(bug)
            assert r["status"] == "skipped"
            assert r["reason"] == "GITHUB_TOKEN missing"


# ===================================================================
# 5. Handoff events
# ===================================================================

class TestHandoff:
    @pytest.fixture
    def mock_orch(self):
        from orchestrator.engine import Orchestrator
        with patch("orchestrator.bus.EventBus") as MockBus:
            mb = MockBus.return_value
            mb.audit_log_path = MagicMock(return_value="/tmp/audit.jsonl")
            o = Orchestrator(root=Path("./tests/test_workspace"), policy=MagicMock())
            o.bus = mb
            yield o

    def test_no_token(self, mock_orch):
        os.environ.pop("GITHUB_TOKEN", None)
        r = mock_orch.process_github_handoff_event({
            "task_id": "TASK-1234", "ci_state": "failed",
            "orchestrator_status": "bug_open", "conclusion": "failure",
            "normalized_ci": {}, "action_required": "create_github_issue_or_comment_pr",
        })
        assert r["status"] == "skipped"
        assert "GITHUB_TOKEN missing" in r["reason"]

    def test_create_issue(self, mock_orch, github_token_set, capsys):
        r = mock_orch.process_github_handoff_event({
            "task_id": "TASK-5678", "ci_state": "failed",
            "orchestrator_status": "bug_open", "conclusion": "failure",
            "normalized_ci": {"status": "completed", "url": "http://example.com/ci/1"},
            "action_required": "create_github_issue_or_comment_pr",
        })
        assert r["status"] == "success"
        assert r["action"] == "simulated_github_issue_creation"
        assert "TASK-5678" in r["issue_title"]
        cap = capsys.readouterr()
        assert "Simulating GitHub API call" in cap.err

    def test_unhandled_action(self, mock_orch, github_token_set):
        r = mock_orch.process_github_handoff_event({
            "task_id": "TASK-9012", "ci_state": "passed",
            "orchestrator_status": "done", "conclusion": "success",
            "normalized_ci": {}, "action_required": "unsupported_action",
        })
        assert r["status"] == "unhandled_action"

    @patch("orchestrator_mcp_server.ORCH")
    @patch("orchestrator_mcp_server._manager_cycle")
    @patch("orchestrator_mcp_server._AUTO_LOOP_STOP")
    @patch("builtins.print")
    def test_auto_manager_loop_processes_handoff(
        self, mock_print, mock_stop, mock_cycle, mock_orch, github_token_set
    ):
        mock_stop.is_set.side_effect = [False, True]
        mock_stop.wait.return_value = None
        mock_orch.poll_events.return_value = [{
            "id": "evt-1", "type": "github.handoff_required",
            "source": "github",
            "payload": {
                "task_id": "TASK-T", "ci_state": "failed",
                "orchestrator_status": "bug_open", "conclusion": "failure",
                "normalized_ci": {"url": "http://t.com/ci"},
                "action_required": "create_github_issue_or_comment_pr",
            },
        }]
        mock_orch.manager_agent.return_value = "manager"
        mock_orch.process_github_handoff_event.return_value = {"status": "success"}
        mock_orch.ack_event.return_value = None

        from orchestrator_mcp_server import _auto_manager_loop
        with patch("orchestrator_mcp_server.fcntl") as mf:
            mf.flock.return_value = None
            with patch("pathlib.Path.open") as mp:
                mp.return_value.__enter__.return_value = MagicMock()
                _auto_manager_loop()

        mock_cycle.assert_called_once_with(strict=True)
        mock_orch.process_github_handoff_event.assert_called_once()
        mock_orch.ack_event.assert_called_once_with(agent="manager", event_id="evt-1")


# ===================================================================
# 6. Full integration test (requires `requests` + subprocesses)
# ===================================================================

requests = pytest.importorskip("requests")


@pytest.fixture
def mcp_server_process():
    mcp_port = _find_available_port()
    env = os.environ.copy()
    env["MCP_PORT"] = str(mcp_port)
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath("tests/mock_mcp_http_server.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=env,
    )
    url = f"http://localhost:{mcp_port}"
    for _ in range(20):
        try:
            if requests.get(url, timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate(); proc.wait(timeout=5)
        pytest.fail("Mock MCP HTTP server did not start")
    yield proc, mcp_port
    proc.terminate(); proc.wait(timeout=5)
    if proc.poll() is None:
        proc.kill()


@pytest.fixture
def github_webhook_listener_thread(mcp_server_process):
    _, mcp_port = mcp_server_process
    listener_port = _find_available_port()
    env = os.environ.copy()
    env["GITHUB_WEBHOOK_PORT"] = str(listener_port)
    env["MCP_PORT"] = str(mcp_port)
    env["MCP_SERVER_URL"] = f"http://localhost:{mcp_port}/mcp"
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath("github_webhook_listener.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, text=True, bufsize=1,
    )
    url = f"http://localhost:{listener_port}"
    for _ in range(40):
        try:
            if requests.get(url, timeout=1).status_code in (200, 404, 405):
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate(); proc.wait(timeout=5)
        pytest.fail("Webhook listener did not start")
    yield proc, listener_port
    proc.terminate(); proc.wait(timeout=5)
    if proc.poll() is None:
        proc.kill()


@patch("orchestrator.engine.Orchestrator._read_json_list", return_value=[])
@patch("orchestrator.engine.Orchestrator._write_json", return_value=None)
def test_github_webhook_listener_integration(
    _mock_write, _mock_read, mcp_server_process, github_webhook_listener_thread
):
    _, listener_port = github_webhook_listener_thread
    payload = {
        "action": "completed",
        "check_run": {
            "id": 999, "external_id": "TASK-integration1",
            "status": "completed", "conclusion": "success",
            "output": {"text": "Integration build passed"},
        },
        "repository": {"full_name": "integration/test"},
    }
    resp = requests.post(
        f"http://localhost:{listener_port}/", json=payload,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "check_run"},
    )
    resp.raise_for_status()
    body = resp.json()
    assert body["status"] == "success"
    assert "mcp_response" in body
    mcp_text = body["mcp_response"]["result"]["content"][0]["text"]
    assert "status" in json.loads(mcp_text)
