import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

import pytest

from orchestrator.engine import Orchestrator
from orchestrator.policy import Policy


@pytest.fixture
def temp_orchestrator(tmp_path: Path) -> Orchestrator:
    policy_content = {
        "agents": {
            "test_agent": {"workstreams": ["backend", "frontend"]},
            "manager": {"workstreams": ["all"]},
        },
        "default_owner": "test_agent",
        "leader_agent": "manager",
        "triggers": {
            "claim_cooldown_seconds": 0,
            "report_retention_days": 30,  # Default for testing cleanup
            "heartbeat_timeout_seconds": 60, # Added missing field
        }
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_content))
    policy = Policy.load(policy_path)
    orchestrator_instance = Orchestrator(root=tmp_path, policy=policy)

    # Register the test_agent and send a heartbeat to make it operational
    orchestrator_instance.register_agent(
        agent="test_agent",
        metadata={
            "client": "pytest_client",
            "model": "pytest_model",
            "cwd": str(orchestrator_instance.root),  # Use orchestrator's root
            "project_root": str(orchestrator_instance.root), # Use orchestrator's root
            "session_id": "test_session",
            "instance_id": "test_agent#test_session",
            "connection_id": "test_connection", # Added missing field
            "team_id": "team-parity",
            "permissions_mode": "full",
            "sandbox_mode": "off",
            "server_version": "test_v1",
            "verification_source": "pytest",
        },
    )
    time.sleep(0.1) # Introduce a small delay
    orchestrator_instance.heartbeat(
        agent="test_agent",
        metadata={
            "current_task": "test_task",
            "project_root": str(orchestrator_instance.root), # Use orchestrator's root
            "team_id": "team-parity",
        },
    )
    return orchestrator_instance


@pytest.fixture(autouse=True)
def mock_now(monkeypatch):
    """Fixture to control datetime.now() for testing time-sensitive logic."""
    _current_time = datetime.now(timezone.utc)

    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz:
                return _current_time.astimezone(tz)
            return _current_time

        @classmethod
        def fromisoformat(cls, date_string):
            return datetime.fromisoformat(date_string)
        
        @classmethod
        def fromtimestamp(cls, timestamp, tz=None):
            return datetime.fromtimestamp(timestamp, tz=tz)

    monkeypatch.setattr("orchestrator.engine.datetime", MockDatetime)
    monkeypatch.setattr("orchestrator.bus.datetime", MockDatetime)

    def set_time(dt: datetime):
        nonlocal _current_time
        _current_time = dt

    return set_time


class TestReportDeduplication:
    def test_ingest_report_deduplicates_same_commit_sha(self, temp_orchestrator: Orchestrator, mock_now, tmp_path: Path):
        mock_now(datetime.now(timezone.utc)) # Initialize time
        
        commit_sha = "abcd123"
        agent_name = "test_agent"
        
        # Create a dummy task for the report
        created_task = temp_orchestrator.create_task(
            title="Test task for deduplication",
            workstream="backend",
            acceptance_criteria=["Do something"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id = created_task["id"] # Capture the dynamic task_id

        # Manually set task status to in_progress to allow report submission
        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)


        report_data = {
            "task_id": task_id,
            "agent": agent_name,
            "commit_sha": commit_sha,
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "First report",
        }

        # First report submission
        first_report_result = temp_orchestrator.ingest_report(report_data)
        assert first_report_result.get("deduplicated") is None
        assert temp_orchestrator.bus.reports_dir.joinpath(f"{task_id}.json").exists()

        # Second report submission with same commit_sha
        second_report_result = temp_orchestrator.ingest_report(report_data)
        assert second_report_result.get("deduplicated") is True

        # Verify that only one report file exists
        report_files = [f for f in temp_orchestrator.bus.reports_dir.iterdir() if f.suffix == ".json" and not f.name.endswith(".json.lock")]
        assert len(report_files) == 1
        assert report_files[0].name == f"{task_id}.json"

        # Check emitted events for deduplication
        events = list(temp_orchestrator.bus.iter_events())
        dedupe_events = [e for e in events if e.get("type") == "task.reported.deduplicated"]
        assert len(dedupe_events) == 1
        assert dedupe_events[0]["payload"]["task_id"] == task_id
        assert dedupe_events[0]["payload"]["commit_sha"] == commit_sha

    def test_ingest_report_does_not_deduplicate_different_commit_sha(self, temp_orchestrator: Orchestrator, mock_now, tmp_path: Path):
        mock_now(datetime.now(timezone.utc)) # Initialize time

        agent_name = "test_agent"

        # Create a dummy task for the report
        created_task = temp_orchestrator.create_task(
            title="Test task for different SHA",
            workstream="backend",
            acceptance_criteria=["Do something"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id = created_task["id"] # Capture the dynamic task_id
        # Manually set task status to in_progress to allow report submission
        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)

        report_data_1 = {
            "task_id": task_id,
            "agent": agent_name,
            "commit_sha": "abcd123",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "First report",
        }
        report_data_2 = {
            "task_id": task_id,
            "agent": agent_name,
            "commit_sha": "efgh456",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Second report",
        }

        # First report submission
        first_report_result = temp_orchestrator.ingest_report(report_data_1)
        assert first_report_result.get("deduplicated") is None
        assert temp_orchestrator.bus.reports_dir.joinpath(f"{task_id}.json").exists()

        # Second report submission with different commit_sha
        second_report_result = temp_orchestrator.ingest_report(report_data_2)
        assert second_report_result.get("deduplicated") is None # Not deduplicated

        # Verify that the report file was updated (overwritten in this case, as it's task_id.json)
        # The current implementation of write_report overwrites the file.
        # So we should expect the latest report to be present.
        report_file_content = json.loads(temp_orchestrator.bus.reports_dir.joinpath(f"{task_id}.json").read_text())
        assert report_file_content["commit_sha"] == "efgh456"

        # Check events: only one task.reported event, and no deduplicated event
        events = list(temp_orchestrator.bus.iter_events())
        reported_events = [e for e in events if e.get("type") == "task.reported"]
        dedupe_events = [e for e in events if e.get("type") == "task.reported.deduplicated"]
        assert len(reported_events) == 2
        assert len(dedupe_events) == 0


class TestReportCleanup:
    def test_cleanup_removes_old_reports(self, temp_orchestrator: Orchestrator, mock_now, tmp_path: Path):
        agent_name = "test_agent"
        
        # Create a dummy task for reports
        created_task_1 = temp_orchestrator.create_task(
            title="Test task for cleanup 1",
            workstream="backend",
            acceptance_criteria=["Clean up"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id_1 = created_task_1["id"] # Capture the dynamic task_id

        # Manually set task status to in_progress to allow report submission
        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id_1:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)

        # Submit an old report (31 days ago)
        old_time = datetime.now(timezone.utc) - timedelta(days=31)
        mock_now(old_time)
        temp_orchestrator.heartbeat(agent_name, metadata={"current_task": task_id_1, "project_root": str(temp_orchestrator.root), "team_id": "team-parity"})
        temp_orchestrator.ingest_report({
            "task_id": task_id_1,
            "agent": agent_name,
            "commit_sha": "oldsha1",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Old report 1",
        })

        # Create another dummy task for reports
        created_task_2 = temp_orchestrator.create_task(
            title="Test task for cleanup 2",
            workstream="backend",
            acceptance_criteria=["Clean up 2"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id_2 = created_task_2["id"] # Capture the dynamic task_id

        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id_2:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)

        # Submit another old report (32 days ago)
        older_time = datetime.now(timezone.utc) - timedelta(days=32)
        mock_now(older_time)
        temp_orchestrator.heartbeat(agent_name, metadata={"current_task": task_id_2, "project_root": str(temp_orchestrator.root), "team_id": "team-parity"})
        temp_orchestrator.ingest_report({
            "task_id": task_id_2,
            "agent": agent_name,
            "commit_sha": "oldsha2",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Old report 2",
        })

        # Create a third dummy task for reports
        created_task_3 = temp_orchestrator.create_task(
            title="Test task for cleanup 3",
            workstream="backend",
            acceptance_criteria=["Clean up 3"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id_3 = created_task_3["id"] # Capture the dynamic task_id

        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id_3:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)

        # Submit a recent report (1 day ago)
        recent_time = datetime.now(timezone.utc) - timedelta(days=1)
        mock_now(recent_time)
        temp_orchestrator.heartbeat(agent_name, metadata={"current_task": task_id_3, "project_root": str(temp_orchestrator.root), "team_id": "team-parity"})
        temp_orchestrator.ingest_report({
            "task_id": task_id_3,
            "agent": agent_name,
            "commit_sha": "newsha",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Recent report",
        })
        
        # Ensure initial state: all 3 reports exist
        report_files_before_cleanup = [f for f in temp_orchestrator.bus.reports_dir.iterdir() if f.suffix == ".json" and not f.name.endswith(".json.lock")]
        assert len(report_files_before_cleanup) == 3

        # Advance time to now for the cleanup logic to correctly identify old reports
        mock_now(datetime.now(timezone.utc))

        # Trigger cleanup via requeue_stale_in_progress_tasks
        temp_orchestrator.requeue_stale_in_progress_tasks(stale_after_seconds=1)

        # Assert only the recent report remains
        report_files_after_cleanup = [f for f in temp_orchestrator.bus.reports_dir.iterdir() if f.suffix == ".json" and not f.name.endswith(".json.lock")]
        assert len(report_files_after_cleanup) == 1
        assert report_files_after_cleanup[0].name == f"{task_id_3}.json"

        # Check emitted events for cleanup
        events = list(temp_orchestrator.bus.iter_events())
        cleaned_event_files = {e["payload"]["file"] for e in events if e.get("type") == "report.cleaned"}
        assert len(cleaned_event_files) == 2
        assert f"{task_id_1}.json" in cleaned_event_files
        assert f"{task_id_2}.json" in cleaned_event_files

    def test_cleanup_respects_retention_policy(self, temp_orchestrator: Orchestrator, mock_now, tmp_path: Path):
        agent_name = "test_agent"
        
        # Override policy for this test: 5 days retention
        temp_orchestrator.policy.triggers["report_retention_days"] = 5

        # Create a dummy task
        created_task_old = temp_orchestrator.create_task(
            title="Test task for policy cleanup old",
            workstream="backend",
            acceptance_criteria=["Policy cleanup"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id_old = created_task_old["id"] # Capture the dynamic task_id
        # Manually set task status to in_progress to allow report submission
        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id_old:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)

        # Submit an old report (6 days ago)
        old_time = datetime.now(timezone.utc) - timedelta(days=6)
        mock_now(old_time)
        temp_orchestrator.heartbeat(agent_name, metadata={"current_task": task_id_old, "project_root": str(temp_orchestrator.root), "team_id": "team-parity"})
        temp_orchestrator.ingest_report({
            "task_id": task_id_old,
            "agent": agent_name,
            "commit_sha": "policyoldsha",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Old report for policy",
        })

        # Create a recent dummy task
        created_task_recent = temp_orchestrator.create_task(
            title="Test task for policy cleanup recent",
            workstream="backend",
            acceptance_criteria=["Policy cleanup recent"],
            owner=agent_name,
            team_id="team-parity",
        )
        task_id_recent = created_task_recent["id"] # Capture the dynamic task_id

        with temp_orchestrator._state_lock():
            tasks = temp_orchestrator._read_json(temp_orchestrator.tasks_path)
            for t in tasks:
                if t["id"] == task_id_recent:
                    t["status"] = "in_progress"
            temp_orchestrator._write_tasks_json(tasks)
            
        # Submit a recent report (2 days ago)
        recent_time = datetime.now(timezone.utc) - timedelta(days=2)
        mock_now(recent_time)
        temp_orchestrator.heartbeat(agent_name, metadata={"current_task": task_id_recent, "project_root": str(temp_orchestrator.root), "team_id": "team-parity"})
        temp_orchestrator.ingest_report({
            "task_id": task_id_recent,
            "agent": agent_name,
            "commit_sha": "policyrecentsha",
            "test_summary": {"passed": 1, "failed": 0, "command": "pytest"},
            "status": "done",
            "notes": "Recent report for policy",
        })

        report_files_before_cleanup = [f for f in temp_orchestrator.bus.reports_dir.iterdir() if f.suffix == ".json" and not f.name.endswith(".json.lock")]
        assert len(report_files_before_cleanup) == 2

        mock_now(datetime.now(timezone.utc)) # Advance time to now

        temp_orchestrator.requeue_stale_in_progress_tasks(stale_after_seconds=1)

        # The old report (6 days old) should be removed, recent (2 days old) should remain
        report_files_after_cleanup = [f for f in temp_orchestrator.bus.reports_dir.iterdir() if f.suffix == ".json" and not f.name.endswith(".json.lock")]
        assert len(report_files_after_cleanup) == 1
        assert report_files_after_cleanup[0].name == f"{task_id_recent}.json"