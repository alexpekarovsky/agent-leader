import json
import os
import pytest
from unittest.mock import MagicMock, patch, ANY

from pathlib import Path

from orchestrator.engine import Orchestrator
from orchestrator.bus import EventBus


@pytest.fixture
def mock_orchestrator():
    with patch('orchestrator.bus.EventBus') as MockEventBus:
        mock_bus = MockEventBus.return_value
        mock_bus.audit_log_path = MagicMock(return_value='/tmp/audit.jsonl')
        orchestrator = Orchestrator(root=Path('./tests/test_workspace'), policy=MagicMock())
        orchestrator.bus = mock_bus
        yield orchestrator

@pytest.fixture
def github_token_set():
    os.environ["GITHUB_TOKEN"] = "test_github_token"
    yield
    del os.environ["GITHUB_TOKEN"]

def test_process_github_handoff_event_no_token(mock_orchestrator):
    payload = {
        "task_id": "TASK-1234",
        "ci_state": "failed",
        "orchestrator_status": "bug_open",
        "conclusion": "failure",
        "normalized_ci": {},
        "action_required": "create_github_issue_or_comment_pr",
    }
    # Ensure GITHUB_TOKEN is not set for this specific test
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]

    result = mock_orchestrator.process_github_handoff_event(payload)
    assert result["status"] == "skipped"
    assert "GITHUB_TOKEN missing" in result["reason"]

def test_process_github_handoff_event_create_issue(mock_orchestrator, github_token_set, capsys):
    payload = {
        "task_id": "TASK-5678",
        "ci_state": "failed",
        "orchestrator_status": "bug_open",
        "conclusion": "failure",
        "normalized_ci": {
            "status": "completed",
            "url": "http://example.com/ci/run/1",
        },
        "action_required": "create_github_issue_or_comment_pr",
    }
    
    result = mock_orchestrator.process_github_handoff_event(payload)
    assert result["status"] == "success"
    assert result["action"] == "simulated_github_issue_creation"
    assert "CI Failed for Task TASK-5678" in result["issue_title"]

    # Verify that print statements indicating simulation are captured
    captured = capsys.readouterr()
    assert "INFO: Simulating GitHub API call to create issue/comment for task TASK-5678" in captured.err
    assert "Issue Title: CI Failed for Task TASK-5678: failure" in captured.err

def test_process_github_handoff_event_unhandled_action(mock_orchestrator, github_token_set):
    payload = {
        "task_id": "TASK-9012",
        "ci_state": "passed",
        "orchestrator_status": "done",
        "conclusion": "success",
        "normalized_ci": {},
        "action_required": "unsupported_action",
    }
    result = mock_orchestrator.process_github_handoff_event(payload)
    assert result["status"] == "unhandled_action"
    assert "No specific handler for action_required: unsupported_action" in result["reason"]


# Test for orchestrator_mcp_server.py integration
@patch('orchestrator_mcp_server.ORCH')
@patch('orchestrator_mcp_server._manager_cycle')
@patch('orchestrator_mcp_server._AUTO_LOOP_STOP')
@patch('builtins.print')
def test_auto_manager_loop_processes_handoff_event(mock_print, mock_auto_loop_stop, mock_manager_cycle, mock_orch, github_token_set):
    # Setup mocks
    mock_auto_loop_stop.is_set.side_effect = [False, True]  # Run loop once then stop
    mock_auto_loop_stop.wait.return_value = None

    # Mock ORCH.poll_events to return a handoff event
    handoff_event = {
        "id": "event-123",
        "type": "github.handoff_required",
        "source": "github",
        "payload": {
            "task_id": "TASK-TEST",
            "ci_state": "failed",
            "orchestrator_status": "bug_open",
            "conclusion": "failure",
            "normalized_ci": {"url": "http://test.com/ci/run"},
            "action_required": "create_github_issue_or_comment_pr",
        },
    }
    mock_orch.poll_events.return_value = [handoff_event]
    mock_orch.manager_agent.return_value = "manager"
    mock_orch.process_github_handoff_event.return_value = {"status": "success"}
    mock_orch.ack_event.return_value = None

    # Call the auto-manager loop directly
    # Need to import the function we're testing from the actual module
    from orchestrator_mcp_server import _auto_manager_loop
    
    # Simulate acquiring the lock
    with patch('orchestrator_mcp_server.fcntl') as mock_fcntl:
        mock_fcntl.flock.return_value = None
        with patch('pathlib.Path.open') as mock_path_open:
            mock_path_open.return_value.__enter__.return_value = MagicMock()
            _auto_manager_loop()

    # Assertions
    mock_manager_cycle.assert_called_once_with(strict=True)
    mock_orch.poll_events.assert_called_once_with(agent="manager", timeout_ms=500)
    mock_orch.process_github_handoff_event.assert_called_once_with(handoff_event["payload"])
    mock_orch.ack_event.assert_called_once_with(agent="manager", event_id="event-123")
    
    # Verify print output for INFO and DEBUG messages
    mock_print.assert_any_call(
        f"INFO: Manager received github.handoff_required event: {handoff_event}", 
        file=ANY, flush=True
    )
    # The exact DEBUG message is harder to assert due to direct print in engine,
    # but INFO message confirms the event was processed.
