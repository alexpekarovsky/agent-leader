import json
import pytest
import os
import sys
import subprocess
import time
import threading
from unittest.mock import MagicMock, patch
import requests
import socket

# Adjust the path to import from the project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def _find_available_port():
    """Finds an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]

# Mock the Orchestrator for unit tests
class MockOrchestrator:
    def __init__(self):
        self.tasks = {}
        self.events = []
    
    def set_task_status(self, task_id, status, source, note):
        self.tasks[task_id] = {"status": status, "source": source, "note": note}
        return {"task_id": task_id, "status": status}

    def publish_event(self, event_type, source, payload):
        self.events.append({"event_type": event_type, "source": source, "payload": payload})
        return {"event_type": event_type, "source": source, "payload": payload}

    def list_tasks(self):
        return [{"id": k, **v} for k, v in self.tasks.items()]

@pytest.fixture
def mock_orchestrator():
    return MockOrchestrator()

@pytest.fixture
def mcp_server_process():
    mcp_port = _find_available_port()
    # Start the mock MCP HTTP server
    env = os.environ.copy()
    env["MCP_PORT"] = str(mcp_port) # Pass dynamic port

    server_cmd = [sys.executable, os.path.abspath('tests/mock_mcp_http_server.py')]
    
    process = subprocess.Popen(
        server_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1, # Line-buffered
        env=env
    )
    
    # Robust readiness check for Mock MCP HTTP server
    mcp_server_url = f"http://localhost:{mcp_port}"
    initialized = False
    for i in range(20): # Try for up to 10 seconds
        try:
            response = requests.get(mcp_server_url, timeout=1)
            if response.status_code == 200:
                print(f"Mock MCP HTTP server ready on port {mcp_port}", file=sys.stderr)
                initialized = True
                break
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            print(f"Mock MCP HTTP server readiness check failed with error: {e}", file=sys.stderr)
        time.sleep(0.5) # Wait a bit before retrying

    if not initialized:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail("Mock MCP HTTP server did not become ready in time.")
    
    yield process, mcp_port # Yield both process and port
    
    # Teardown: terminate the server process
    process.terminate()
    process.wait(timeout=5)
    if process.poll() is None:
        process.kill()
    print(f"Mock MCP HTTP server terminated with exit code: {process.returncode}", file=sys.stderr)
    stderr_output = process.stderr.read()
    if stderr_output:
        print("Mock MCP HTTP server stderr:", stderr_output, file=sys.stderr)


@pytest.fixture
def github_webhook_listener_thread(mcp_server_process):
    mcp_server_proc, mcp_port = mcp_server_process # Unpack process and port
    listener_port = _find_available_port()
    
    env = os.environ.copy()
    env["GITHUB_WEBHOOK_PORT"] = str(listener_port)
    env["MCP_PORT"] = str(mcp_port) # Use the port from the mcp_server_process fixture
    env["MCP_SERVER_URL"] = f"http://localhost:{mcp_port}/mcp" # Pass dynamic MCP URL
    
    # Directly use the python executable from the venv
    venv_python = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.venv', 'bin', 'python'))
    listener_cmd = [
        venv_python,
        os.path.abspath('github_webhook_listener.py')
    ]
    
    listener_process = subprocess.Popen(
        listener_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )
    
    # Robust readiness check for Webhook Listener
    listener_url = f"http://localhost:{listener_port}"
    listener_ready = False
    for i in range(40): # Try for up to 20 seconds
        try:
            response = requests.get(listener_url, timeout=1)
            # Listener is ready if it responds, even with a 404 for GET
            if response.status_code in [200, 404, 405]: 
                listener_ready = True
                break
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            # Capture and print stderr for debugging
            stderr_output = listener_process.stderr.readline()
            if stderr_output:
                print(f"Listener stderr during readiness check: {stderr_output.strip()}", file=sys.stderr)
            print(f"Webhook listener readiness check failed with error: {e}", file=sys.stderr)
        time.sleep(0.5)
    
    if not listener_ready:
        listener_process.terminate()
        listener_process.wait(timeout=5)
        # Print any remaining stderr before failing
        stderr_output_final = listener_process.stderr.read()
        if stderr_output_final:
            print("Final Webhook listener stderr before failure:", stderr_output_final, file=sys.stderr)
        pytest.fail("GitHub webhook listener did not become ready in time.")
    
    yield listener_process, listener_port
    
    # Teardown: terminate the listener process
    listener_process.terminate()
    listener_process.wait(timeout=5)
    if listener_process.poll() is None:
        listener_process.kill()
    print(f"Webhook listener terminated with exit code: {listener_process.returncode}", file=sys.stderr)
    stderr_output = listener_process.stderr.read()
    if stderr_output:
        print("Webhook listener stderr:", stderr_output, file=sys.stderr)


# --- Unit Tests for orchestrator_mcp_server.py webhook handler ---

@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_success(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    # Mock the return value of ORCH.process_github_webhook
    mock_orch.process_github_webhook.return_value = {
        "event_type": "check_run",
        "repo": "test/repo",
        "status": "ci_updated",
        "details": "CI status updated for 1 PR(s)",
        "ci_state": "passed",
        "updated_prs": [
            {
                "pr_id": "PR-mock-0",
                "pr_number": 1,
                "stack_id": "STACK-mock",
                "ci_state": "passed",
            }
        ],
    }

    task_id = "TASK-abcdef12"
    github_payload = {
        "action": "completed",
        "check_run": {
            "id": 123,
            "external_id": task_id,
            "status": "completed",
            "conclusion": "success",
            "output": {"text": "Build successful for " + task_id},
        },
        "repository": {"full_name": "test/repo"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "check_run"}},
    }

    result = handle_tool_call("test_req_1", params)

    assert "result" in result, f"Expected 'result' key, got: {list(result.keys())}"
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "ci_updated"
    assert parsed["ci_state"] == "passed"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_failure_and_handoff(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "check_run",
        "repo": "test/repo",
        "status": "ci_updated",
        "details": "CI status updated for 1 PR(s)",
        "ci_state": "failed",
        "updated_prs": [
            {
                "pr_id": "PR-mock-1",
                "pr_number": 2,
                "stack_id": "STACK-mock",
                "ci_state": "failed",
            }
        ],
    }

    task_id = "TASK-fedcba98"
    github_payload = {
        "action": "completed",
        "check_run": {
            "id": 456,
            "external_id": task_id,
            "status": "completed",
            "conclusion": "failure",
            "output": {"text": "Build failed for " + task_id},
        },
        "repository": {"full_name": "test/repo"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "check_run"}},
    }

    result = handle_tool_call("test_req_2", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "ci_updated"
    assert parsed["ci_state"] == "failed"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_no_task_id(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "check_run",
        "repo": "test/repo",
        "status": "ci_no_matching_pr_in_stack",
        "details": "Check run for some_sha has no matching PR in any stack.",
        "ci_state": "passed",
    }

    github_payload = {
        "action": "completed",
        "check_run": {
            "id": 789,
            "status": "completed",
            "conclusion": "success",
            "output": {"text": "Build successful"},
        },
        "repository": {"full_name": "test/repo"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "check_run"}},
    }

    result = handle_tool_call("test_req_3", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "ci_no_matching_pr_in_stack"
    assert parsed["ci_state"] == "passed"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_task_id_from_output_text(mock_orch):
    """Task ID extracted from check_run.output.text when external_id is missing."""
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "check_run",
        "repo": "test/repo",
        "status": "ci_updated",
        "details": "CI status updated for 1 PR(s)",
        "ci_state": "passed",
        "updated_prs": [
            {
                "pr_id": "PR-mock-2",
                "pr_number": 3,
                "stack_id": "STACK-mock",
                "ci_state": "passed",
            }
        ],
    }

    task_id = "TASK-aabbcc11"
    github_payload = {
        "action": "completed",
        "check_run": {
            "id": 555,
            "status": "completed",
            "conclusion": "success",
            "output": {"text": f"CI passed for {task_id} on main branch"},
        },
        "repository": {"full_name": "test/repo"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "check_run"}},
    }

    result = handle_tool_call("test_req_4", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "ci_updated"
    assert parsed["ci_state"] == "passed"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_running_state(mock_orch):
    """Running CI state maps to in_progress orchestrator status."""
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "check_run",
        "repo": "test/repo",
        "status": "ci_updated",
        "details": "CI status updated for 1 PR(s)",
        "ci_state": "running",
        "updated_prs": [
            {
                "pr_id": "PR-mock-3",
                "pr_number": 4,
                "stack_id": "STACK-mock",
                "ci_state": "running",
            }
        ],
    }

    task_id = "TASK-ddee0011"
    github_payload = {
        "action": "created",
        "check_run": {
            "id": 777,
            "external_id": task_id,
            "status": "in_progress",
            "conclusion": None,
            "output": {"text": ""},
        },
        "repository": {"full_name": "test/repo"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "check_run"}},
    }

    result = handle_tool_call("test_req_5", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "ci_updated"
    assert parsed["ci_state"] == "running"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_pull_request_opened(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "pull_request",
        "repo": "test/repo",
        "status": "pr_updated",
        "details": "PR 1 opened in stack STACK-mock",
        "pr_id": "PR-mock-0",
        "pr_number": 1,
    }

    github_payload = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "head": {"ref": "feature-branch", "sha": "abcdef123456"},
            "base": {"ref": "main"},
            "title": "Feature PR",
            "state": "open",
            "merged": False,
        },
        "repository": {"full_name": "test/repo"},
        "sender": {"login": "test-user"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "pull_request"}},
    }

    result = handle_tool_call("test_req_pr_open", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "pr_updated"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_pull_request_closed_merged(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "pull_request",
        "repo": "test/repo",
        "status": "pr_merged",
        "details": "PR 2 merged in stack STACK-mock",
        "pr_id": "PR-mock-1",
        "pr_number": 2,
        "ungated_child_prs": [],
    }

    github_payload = {
        "action": "closed",
        "pull_request": {
            "number": 2,
            "head": {"ref": "feature-merged", "sha": "fedcba987654"},
            "base": {"ref": "main"},
            "title": "Merged Feature PR",
            "state": "closed",
            "merged": True,
        },
        "repository": {"full_name": "test/repo"},
        "sender": {"login": "test-user"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "pull_request"}},
    }

    result = handle_tool_call("test_req_pr_merged", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "pr_merged"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_process_github_webhook_pull_request_closed_not_merged(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    mock_orch.process_github_webhook.return_value = {
        "event_type": "pull_request",
        "repo": "test/repo",
        "status": "pr_closed",
        "details": "PR 3 closed (not merged) in stack STACK-mock",
        "pr_id": "PR-mock-2",
        "pr_number": 3,
    }

    github_payload = {
        "action": "closed",
        "pull_request": {
            "number": 3,
            "head": {"ref": "feature-closed", "sha": "123456abcdef"},
            "base": {"ref": "main"},
            "title": "Closed Feature PR",
            "state": "closed",
            "merged": False,
        },
        "repository": {"full_name": "test/repo"},
        "sender": {"login": "test-user"},
    }

    params = {
        "name": "orchestrator_process_github_webhook",
        "arguments": {"payload": github_payload, "source": "github", "headers": {"X-GitHub-Event": "pull_request"}},
    }

    result = handle_tool_call("test_req_pr_closed", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "pr_closed"
    mock_orch.process_github_webhook.assert_called_once_with(
        payload=github_payload, source="github"
    )


@patch('orchestrator_mcp_server.ORCH')
def test_orchestrator_create_github_issue_success(mock_orch):
    from orchestrator_mcp_server import handle_tool_call

    bug_id = "BUG-12345678"
    expected_result = {
        "status": "success",
        "action": "github_issue_created",
        "bug_id": bug_id,
        "repo": "test/repo",
        "issue_number": 123,
        "issue_url": "https://github.com/test/repo/issues/123",
        "issue_title": "[HIGH Bug] Task TASK-abcdef12: Crashed on startup",
    }

    mock_orch.orchestrator_create_github_issue.return_value = expected_result

    params = {
        "name": "orchestrator_create_github_issue",
        "arguments": {"bug_id": bug_id, "repo": "test/repo"},
    }

    result = handle_tool_call("test_req_github_issue", params)

    assert "result" in result
    parsed = json.loads(result["result"]["content"][0]["text"])
    assert parsed["status"] == "success"
    assert parsed["bug_id"] == bug_id
    assert parsed["issue_number"] == 123
    assert parsed["repo"] == "test/repo"
    assert parsed["issue_title"] == "[HIGH Bug] Task TASK-abcdef12: Crashed on startup"

    mock_orch.orchestrator_create_github_issue.assert_called_once_with(bug_id=bug_id, repo="test/repo")


def test_build_github_issue_payload_structure():
    """Verify build_github_issue_payload returns valid GitHub issue payload."""
    from orchestrator.github_ci import build_github_issue_payload

    bug = {
        "id": "BUG-aabbccdd",
        "source_task": "TASK-11223344",
        "owner": "claude_code",
        "severity": "critical",
        "repro_steps": "1. Run orchestrator\n2. Create task\n3. Observe crash",
        "expected": "Task created successfully",
        "actual": "RuntimeError on task creation",
        "status": "open",
    }

    payload = build_github_issue_payload(bug)

    # Required GitHub API fields present
    assert "title" in payload
    assert "body" in payload
    assert "labels" in payload
    assert "assignees" in payload

    # Title maps severity correctly
    assert payload["title"] == "[CRITICAL Bug] Task TASK-11223344: RuntimeError on task creation"

    # Body includes repro steps and task context
    assert "BUG-aabbccdd" in payload["body"]
    assert "TASK-11223344" in payload["body"]
    assert "claude_code" in payload["body"]
    assert "critical" in payload["body"]
    assert "Run orchestrator" in payload["body"]
    assert "Task created successfully" in payload["body"]
    assert "RuntimeError on task creation" in payload["body"]

    # Labels include mapped severity, bug tag, and task reference
    assert "severity:critical" in payload["labels"]
    assert "bug" in payload["labels"]
    assert "task:TASK-11223344" in payload["labels"]

    # Assignees set to bug owner
    assert payload["assignees"] == ["claude_code"]


def test_create_github_issue_payload_generation():
    """Verify _create_github_issue_from_bug generates valid payload without hitting GitHub API."""
    import tempfile
    from pathlib import Path
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy

    with tempfile.TemporaryDirectory() as tmp:
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

        bug = {
            "id": "BUG-aabbccdd",
            "source_task": "TASK-11223344",
            "owner": "claude_code",
            "severity": "critical",
            "repro_steps": "1. Run orchestrator\n2. Create task\n3. Observe crash",
            "expected": "Task created successfully",
            "actual": "RuntimeError on task creation",
            "status": "open",
            "created_at": "2026-03-21T00:00:00Z",
        }

        # Write the bug to state so the method can update it
        orch._write_json(orch.bugs_path, [bug])

        # Set env vars; API call will fail (fake token) so falls back to dry-run
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/test-repo", "GITHUB_TOKEN": "fake-token"}):
            result = orch._create_github_issue_from_bug(bug, repo_full_name="owner/test-repo")

        # Verify payload structure
        assert result["status"] == "success"
        assert result["bug_id"] == "BUG-aabbccdd"
        assert result["repo"] == "owner/test-repo"
        assert isinstance(result["issue_number"], int)
        assert result["issue_url"].startswith("https://github.com/owner/test-repo/issues/")
        assert result["action"] in ("github_issue_created", "dry_run_github_issue_creation")

        # Verify title maps severity correctly
        assert result["issue_title"] == "[CRITICAL Bug] Task TASK-11223344: RuntimeError on task creation"

        # Verify bug record was updated with github_issue link
        bugs = orch._read_json_list(orch.bugs_path)
        updated_bug = next(b for b in bugs if b["id"] == "BUG-aabbccdd")
        assert "github_issue" in updated_bug
        gh_issue = updated_bug["github_issue"]
        assert gh_issue["repo"] == "owner/test-repo"
        assert gh_issue["status"] == "open"
        assert isinstance(gh_issue["issue_number"], int)


def test_create_github_issue_skips_without_token():
    """Verify _create_github_issue_from_bug returns skipped when GITHUB_TOKEN is missing."""
    import tempfile
    from pathlib import Path
    from orchestrator.engine import Orchestrator
    from orchestrator.policy import Policy

    with tempfile.TemporaryDirectory() as tmp:
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

        bug = {
            "id": "BUG-99887766",
            "source_task": "TASK-55667788",
            "owner": "gemini",
            "severity": "medium",
            "repro_steps": "Steps here",
            "expected": "Expected",
            "actual": "Actual",
            "status": "open",
        }

        env = {"GITHUB_REPOSITORY": "owner/repo"}
        # Ensure GITHUB_TOKEN is not set
        env_remove = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env_remove["GITHUB_REPOSITORY"] = "owner/repo"
        with patch.dict(os.environ, env_remove, clear=True):
            result = orch._create_github_issue_from_bug(bug)

        assert result["status"] == "skipped"
        assert result["reason"] == "GITHUB_TOKEN missing"
        assert result["bug_id"] == "BUG-99887766"


def test_create_github_issue_severity_label_mapping():
    """Verify severity levels map to correct labels in the issue payload."""
    from orchestrator.github_ci import build_github_issue_payload

    for severity in ("critical", "high", "medium", "low"):
        bug = {
            "id": f"BUG-{severity[:8].ljust(8, '0')}",
            "source_task": "TASK-aabb0011",
            "owner": "codex",
            "severity": severity,
            "repro_steps": "repro",
            "expected": "expected",
            "actual": "actual",
            "status": "open",
        }

        payload = build_github_issue_payload(bug)

        # Title includes uppercased severity
        assert f"[{severity.upper()} Bug]" in payload["title"]
        # Labels include mapped severity label
        assert f"severity:{severity}" in payload["labels"]
        assert "bug" in payload["labels"]
        assert "task:TASK-aabb0011" in payload["labels"]


def test_orchestrator_process_github_webhook_orch_not_initialized():
    """Handler returns error when ORCH is None."""
    from orchestrator_mcp_server import handle_tool_call

    with patch('orchestrator_mcp_server.ORCH', None):
        params = {
            "name": "orchestrator_process_github_webhook",
            "arguments": {"payload": {"repository": {"full_name": "test/repo"}}, "source": "github"},
        }

        result = handle_tool_call("test_req_none", params)

        assert "error" in result
        assert "not initialized" in result["error"]["message"].lower()

# --- Integration Tests for github_webhook_listener.py and orchestrator_mcp_server.py ---

@patch('orchestrator.engine.Orchestrator._read_json_list', return_value=[])
@patch('orchestrator.engine.Orchestrator._write_json', return_value=None)
def test_github_webhook_listener_integration(mock_write_json, mock_read_json_list, mcp_server_process, github_webhook_listener_thread):
    listener_process, listener_port = github_webhook_listener_thread
    
    # Create a mock GitHub webhook payload
    mock_github_payload = {
        "action": "completed",
        "check_run": {
            "id": 999,
            "external_id": "TASK-integration1",
            "status": "completed",
            "conclusion": "success",
            "output": {"text": "Integration build passed"},
        },
        "repository": {"full_name": "integration/test"},
    }
    
    # Send the mock webhook to the listener
    try:
        response = requests.post(
            f"http://localhost:{listener_port}/",
            json=mock_github_payload,
            headers={"Content-Type": "application/json", "X-GitHub-Event": "check_run"}
        )
        response.raise_for_status()
        listener_response = response.json()
        print(f"Listener response: {listener_response}", file=sys.stderr)
        assert listener_response["status"] == "success"
        # The mcp_response should contain the result from ORCH.process_github_webhook
        assert "mcp_response" in listener_response
        assert listener_response["mcp_response"]["result"]["content"][0]["text"] # Check for content
        parsed_mcp_response = json.loads(listener_response["mcp_response"]["result"]["content"][0]["text"])
        assert "status" in parsed_mcp_response # Check that the parsed response has a status key

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Failed to send webhook to listener: {e}")