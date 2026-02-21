from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.bus import EventBus
from orchestrator.policy import Policy

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None


@dataclass
class Orchestrator:
    root: Path
    policy: Policy

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.bus = EventBus(self.root / "bus")
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_path = self.state_dir / "tasks.json"
        self.bugs_path = self.state_dir / "bugs.json"
        self.blockers_path = self.state_dir / "blockers.json"
        self.cursors_path = self.state_dir / "event_cursors.json"
        self.acks_path = self.state_dir / "event_acks.json"
        self.agents_path = self.state_dir / "agents.json"
        self.stale_notices_path = self.state_dir / "stale_notices.json"
        self.claim_overrides_path = self.state_dir / "claim_overrides.json"
        self.report_retry_queue_path = self.state_dir / "report_retry_queue.json"
        self.roles_path = self.state_dir / "roles.json"
        self.decisions_dir = self.root / "decisions"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.state_lock_path = self.state_dir / ".state.lock"
        if fcntl is None:
            print(
                "WARNING: fcntl unavailable; state lock disabled. Multi-process safety is degraded.",
                file=sys.stderr,
                flush=True,
            )

    @contextmanager
    def _state_lock(self) -> Any:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.state_lock_path.open("a+", encoding="utf-8") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def bootstrap(self) -> None:
        if not self.tasks_path.exists():
            self.tasks_path.write_text("[]\n", encoding="utf-8")
        if not self.bugs_path.exists():
            self.bugs_path.write_text("[]\n", encoding="utf-8")
        if not self.blockers_path.exists():
            self.blockers_path.write_text("[]\n", encoding="utf-8")
        if not self.cursors_path.exists():
            self.cursors_path.write_text("{}\n", encoding="utf-8")
        if not self.acks_path.exists():
            self.acks_path.write_text("{}\n", encoding="utf-8")
        if not self.agents_path.exists():
            self.agents_path.write_text("{}\n", encoding="utf-8")
        if not self.stale_notices_path.exists():
            self.stale_notices_path.write_text("{}\n", encoding="utf-8")
        if not self.claim_overrides_path.exists():
            self.claim_overrides_path.write_text("{}\n", encoding="utf-8")
        if not self.report_retry_queue_path.exists():
            self.report_retry_queue_path.write_text("[]\n", encoding="utf-8")
        if not self.roles_path.exists():
            self.roles_path.write_text(
                json.dumps({"leader": self.policy.manager(), "team_members": []}, indent=2) + "\n",
                encoding="utf-8",
            )
        self.bus.emit(
            "orchestrator.bootstrapped",
            {"policy": self.policy.name, "manager": self.policy.manager()},
            source="orchestrator",
        )

    def connect_team_members(
        self,
        source: str,
        team_members: List[str],
        timeout_seconds: int = 60,
        poll_interval_seconds: int = 2,
        stale_after_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            raise ValueError(f"leader_mismatch: source={source}, current_leader={manager}")
        stale_after = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
        requested = sorted({w.strip() for w in team_members if isinstance(w, str) and w.strip()})
        if not requested:
            raise ValueError("team_members must contain at least one non-empty agent id")

        started_at = time.time()
        deadline = started_at + max(1, int(timeout_seconds))

        # One manager signal that team_members should register + heartbeat now.
        self.publish_event(
            event_type="manager.connect_team_members",
            source=source,
            payload={"team_members": requested, "timeout_seconds": int(timeout_seconds)},
            audience=requested,
        )

        connected: List[str] = []
        while time.time() < deadline:
            agents = self.list_agents(active_only=False, stale_after_seconds=stale_after)
            active = {
                item.get("agent")
                for item in agents
                if (
                    item.get("agent") in requested
                    and item.get("status") == "active"
                    and bool(item.get("verified"))
                    and bool(item.get("same_project"))
                )
            }
            connected = sorted(active)
            if len(connected) == len(requested):
                break
            time.sleep(max(1, int(poll_interval_seconds)))

        missing = [team_member for team_member in requested if team_member not in set(connected)]
        status = "connected" if not missing else "timeout"
        diagnostics = {
            team_member: self._team_member_connect_diagnostic(team_member=team_member, stale_after_seconds=stale_after)
            for team_member in requested
        }

        self.publish_event(
            event_type="manager.connect_team_members.result",
            source=source,
            payload={"status": status, "connected": connected, "missing": missing, "diagnostics": diagnostics},
            audience=requested,
        )

        return {
            "status": status,
            "requested": requested,
            "connected": connected,
            "missing": missing,
            "diagnostics": diagnostics,
            "timeout_seconds": int(timeout_seconds),
            "elapsed_seconds": int(time.time() - started_at),
        }

    def create_task(
        self,
        title: str,
        workstream: str,
        acceptance_criteria: List[str],
        description: str = "",
        owner: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            task_id = f"TASK-{uuid.uuid4().hex[:8]}"
            resolved_owner = owner or self.policy.task_owner_for(workstream)
            duplicate = self._find_duplicate_open_task(
                tasks=tasks,
                title=title,
                workstream=workstream,
                owner=resolved_owner,
            )
            if duplicate is not None:
                echoed = dict(duplicate)
                echoed["deduplicated"] = True
                echoed["dedupe_reason"] = "matching open task already exists"
                return echoed

            task = {
                "id": task_id,
                "title": title,
                "description": description,
                "workstream": workstream,
                "owner": resolved_owner,
                "status": "assigned",
                "acceptance_criteria": acceptance_criteria,
                "created_at": self._now(),
                "updated_at": self._now(),
            }
            tasks.append(task)
            self._write_json(self.tasks_path, tasks)

        self.bus.write_command(
            task_id,
            {
                "task_id": task_id,
                "owner": resolved_owner,
                "title": title,
                "description": description,
                "workstream": workstream,
                "acceptance_criteria": acceptance_criteria,
                "required_report": [
                    "task_id",
                    "agent",
                    "commit_sha",
                    "test_summary",
                    "status",
                    "notes",
                ],
            },
        )

        self.bus.emit(
            "task.assigned",
            {
                "task_id": task_id,
                "owner": resolved_owner,
                "workstream": workstream,
            },
            source=self.manager_agent(),
        )
        return task

    def dedupe_open_tasks(self, source: str) -> Dict[str, Any]:
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            open_statuses = {"assigned", "in_progress", "reported", "bug_open", "blocked"}
            groups: Dict[str, List[Dict[str, Any]]] = {}

            for task in tasks:
                if task.get("status") not in open_statuses:
                    continue
                key = self._task_fingerprint(
                    title=str(task.get("title", "")),
                    workstream=str(task.get("workstream", "")),
                    owner=str(task.get("owner", "")),
                )
                groups.setdefault(key, []).append(task)

            changed = False
            deduped: List[Dict[str, str]] = []
            for _, group in groups.items():
                if len(group) <= 1:
                    continue
                # Keep the oldest task as canonical; close newer duplicates.
                ordered = sorted(group, key=lambda item: str(item.get("created_at", "")))
                keeper = ordered[0]
                for dup in ordered[1:]:
                    dup["status"] = "duplicate_closed"
                    dup["duplicate_of"] = keeper.get("id")
                    dup["updated_at"] = self._now()
                    changed = True
                    entry = {"task_id": str(dup.get("id", "")), "duplicate_of": str(keeper.get("id", ""))}
                    deduped.append(entry)
                    self.bus.emit("task.duplicate_closed", entry, source=source)

            if changed:
                self._write_json(self.tasks_path, tasks)

        return {"deduped_count": len(deduped), "deduped": deduped}

    def list_tasks(self) -> List[Dict[str, Any]]:
        return self._read_json(self.tasks_path)

    def list_tasks_for_owner(self, owner: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = [task for task in self.list_tasks() if task.get("owner") == owner]
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return tasks

    def claim_next_task(self, owner: str) -> Optional[Dict[str, Any]]:
        self._assert_agent_operational(owner)
        # Treat a claim attempt as proof-of-life from the team_member.
        with self._state_lock():
            self._refresh_agent_presence_unlocked(owner)
            tasks = self._read_json(self.tasks_path)
            overrides = self._read_json(self.claim_overrides_path)
            if not isinstance(overrides, dict):
                overrides = {}
            override_task_id = overrides.get(owner)
            if isinstance(override_task_id, str) and override_task_id.strip():
                forced = next((t for t in tasks if t.get("id") == override_task_id and t.get("owner") == owner), None)
                if forced and forced.get("status") in {"assigned", "bug_open"}:
                    forced["status"] = "in_progress"
                    forced["updated_at"] = self._now()
                    self._write_json(self.tasks_path, tasks)
                    del overrides[owner]
                    self._write_json(self.claim_overrides_path, overrides)
                    self.bus.emit(
                        "task.claimed",
                        {"task_id": forced["id"], "owner": owner, "via": "manager_override"},
                        source=owner,
                    )
                    return forced
                # Override no longer valid; clear it and continue normal claim order.
                del overrides[owner]
                self._write_json(self.claim_overrides_path, overrides)

            for task in tasks:
                if task.get("owner") != owner:
                    continue
                if task.get("status") not in {"assigned", "bug_open"}:
                    continue

                task["status"] = "in_progress"
                task["updated_at"] = self._now()
                self._write_json(self.tasks_path, tasks)
                self.bus.emit(
                    "task.claimed",
                    {"task_id": task["id"], "owner": owner},
                    source=owner,
                )
                return task
        return None

    def set_claim_override(self, agent: str, task_id: str, source: str) -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            raise ValueError(f"leader_mismatch: source={source}, current_leader={manager}")
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            task = next((t for t in tasks if t.get("id") == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task.get("owner") != agent:
                raise ValueError(f"Task owner '{task.get('owner')}' does not match target agent '{agent}'")

            overrides = self._read_json(self.claim_overrides_path)
            if not isinstance(overrides, dict):
                overrides = {}
            overrides[agent] = task_id
            self._write_json(self.claim_overrides_path, overrides)
        self.bus.emit(
            "manager.claim_override",
            {"agent": agent, "task_id": task_id},
            source=source,
        )
        return {"ok": True, "agent": agent, "task_id": task_id}

    def set_task_status(self, task_id: str, status: str, source: str, note: str = "") -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            self._assert_agent_operational(source)
        normalized = str(status).strip().lower()
        # Completion must flow through ingest_report/submit_report so manager validation
        # can enforce commit + test evidence and emit consistent report events.
        if normalized in {"done", "reported"} and source != self.manager_agent():
            raise ValueError("Use orchestrator_submit_report for completion/report transitions")
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            task = next((t for t in tasks if t["id"] == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            owner = str(task.get("owner", ""))
            if source not in {owner, manager}:
                raise ValueError(
                    f"unauthorized_status_update: source={source}, task_owner={owner}, current_leader={manager}"
                )

            task["status"] = status
            task["updated_at"] = self._now()
            self._write_json(self.tasks_path, tasks)
        self.bus.emit(
            "task.status_changed",
            {"task_id": task_id, "status": status, "owner": task["owner"], "note": note},
            source=source,
        )
        return task

    def ingest_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        required = {"task_id", "agent", "commit_sha", "test_summary", "status"}
        missing = sorted(required - set(report))
        if missing:
            raise ValueError(f"Missing report fields: {', '.join(missing)}")
        self._validate_report_payload(report)
        self._assert_agent_operational(str(report.get("agent", "")))

        task_id = report["task_id"]
        with self._state_lock():
            self._refresh_agent_presence_unlocked(str(report["agent"]))
            tasks = self._read_json(self.tasks_path)
            task = next((item for item in tasks if item["id"] == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task.get("owner") != report["agent"]:
                raise ValueError(
                    f"Report agent '{report['agent']}' does not match task owner '{task.get('owner')}'"
                )

            self.bus.write_report(task_id=task_id, report=report)

            task["status"] = "reported"
            task["updated_at"] = self._now()
            self._write_json(self.tasks_path, tasks)

        self.bus.emit(
            "task.reported",
            {"task_id": task_id, "agent": report["agent"], "status": report["status"]},
            source=report["agent"],
        )
        return report

    def enqueue_report_retry(self, report: Dict[str, Any], error: str) -> Dict[str, Any]:
        now = self._now()
        entry: Dict[str, Any]
        with self._state_lock():
            queue = self._read_json(self.report_retry_queue_path)
            if not isinstance(queue, list):
                queue = []

            report_task_id = str(report.get("task_id", ""))
            report_agent = str(report.get("agent", ""))
            existing = next(
                (
                    item
                    for item in queue
                    if item.get("status") == "pending"
                    and item.get("report", {}).get("task_id") == report_task_id
                    and item.get("report", {}).get("agent") == report_agent
                ),
                None,
            )
            if existing is not None:
                existing["report"] = dict(report)
                existing["last_error"] = str(error)
                existing["updated_at"] = now
                entry = dict(existing)
            else:
                entry = {
                    "id": f"RPTQ-{uuid.uuid4().hex[:8]}",
                    "status": "pending",
                    "report": dict(report),
                    "attempts": 0,
                    "last_error": str(error),
                    "created_at": now,
                    "updated_at": now,
                    "next_retry_at": now,
                }
                queue.append(entry)
            self._write_json(self.report_retry_queue_path, queue)

        self.bus.emit(
            "report.retry_queued",
            {
                "queue_id": entry.get("id"),
                "task_id": report.get("task_id"),
                "agent": report.get("agent"),
                "error": str(error),
            },
            source="orchestrator",
        )
        return entry

    def process_report_retry_queue(
        self,
        max_attempts: int = 20,
        base_backoff_seconds: int = 15,
        max_backoff_seconds: int = 300,
        limit: int = 20,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        due_items: List[Dict[str, Any]] = []
        with self._state_lock():
            queue = self._read_json(self.report_retry_queue_path)
            if not isinstance(queue, list):
                queue = []
            for item in queue:
                if item.get("status") != "pending":
                    continue
                retry_at_raw = str(item.get("next_retry_at", ""))
                try:
                    retry_at = datetime.fromisoformat(retry_at_raw)
                except Exception:
                    retry_at = now
                if retry_at <= now:
                    due_items.append(dict(item))
                if len(due_items) >= max(1, int(limit)):
                    break

        processed: List[Dict[str, Any]] = []
        for item in due_items:
            queue_id = str(item.get("id", ""))
            report = item.get("report", {}) if isinstance(item.get("report"), dict) else {}
            attempts = int(item.get("attempts", 0))
            try:
                result = self.ingest_report(report)
                with self._state_lock():
                    queue = self._read_json(self.report_retry_queue_path)
                    if not isinstance(queue, list):
                        queue = []
                    for entry in queue:
                        if str(entry.get("id", "")) != queue_id:
                            continue
                        entry["status"] = "submitted"
                        entry["updated_at"] = self._now()
                        entry["submitted_at"] = self._now()
                        entry["last_error"] = ""
                        break
                    self._write_json(self.report_retry_queue_path, queue)
                processed.append({"queue_id": queue_id, "status": "submitted", "result": result})
                self.bus.emit(
                    "report.retry_submitted",
                    {"queue_id": queue_id, "task_id": report.get("task_id"), "agent": report.get("agent")},
                    source="orchestrator",
                )
            except Exception as exc:
                attempts += 1
                backoff = min(max_backoff_seconds, max(1, base_backoff_seconds) * (2 ** max(0, attempts - 1)))
                next_retry = datetime.now(timezone.utc).timestamp() + backoff
                next_retry_iso = datetime.fromtimestamp(next_retry, tz=timezone.utc).isoformat()
                terminal = attempts >= max(1, int(max_attempts))
                with self._state_lock():
                    queue = self._read_json(self.report_retry_queue_path)
                    if not isinstance(queue, list):
                        queue = []
                    for entry in queue:
                        if str(entry.get("id", "")) != queue_id:
                            continue
                        entry["attempts"] = attempts
                        entry["last_error"] = str(exc)
                        entry["updated_at"] = self._now()
                        entry["next_retry_at"] = next_retry_iso
                        if terminal:
                            entry["status"] = "failed"
                        break
                    self._write_json(self.report_retry_queue_path, queue)
                processed.append(
                    {
                        "queue_id": queue_id,
                        "status": "failed" if terminal else "retrying",
                        "attempts": attempts,
                        "error": str(exc),
                        "next_retry_at": next_retry_iso,
                    }
                )
                self.bus.emit(
                    "report.retry_failed" if terminal else "report.retry_retrying",
                    {
                        "queue_id": queue_id,
                        "task_id": report.get("task_id"),
                        "agent": report.get("agent"),
                        "attempts": attempts,
                        "error": str(exc),
                        "next_retry_at": next_retry_iso,
                    },
                    source="orchestrator",
                )

        with self._state_lock():
            queue = self._read_json(self.report_retry_queue_path)
            if not isinstance(queue, list):
                queue = []
        pending = len([item for item in queue if item.get("status") == "pending"])
        failed = len([item for item in queue if item.get("status") == "failed"])
        submitted = len([item for item in queue if item.get("status") == "submitted"])
        return {
            "processed": processed,
            "pending": pending,
            "failed": failed,
            "submitted": submitted,
        }

    def requeue_stale_in_progress_tasks(self, stale_after_seconds: int = 1800) -> List[Dict[str, Any]]:
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                agents = {}
            now = datetime.now(timezone.utc)
            requeued: List[Dict[str, Any]] = []
            changed = False

            for task in tasks:
                if task.get("status") != "in_progress":
                    continue

                owner = task.get("owner")
                agent = agents.get(owner, {}) if isinstance(owner, str) else {}
                last_seen_raw = agent.get("last_seen")
                if not last_seen_raw:
                    continue

                age = self._age_seconds(last_seen_raw, now=now)
                if age is None or age <= stale_after_seconds:
                    continue

                task["status"] = "assigned"
                task["updated_at"] = self._now()
                changed = True
                record = {
                    "task_id": task.get("id"),
                    "owner": owner,
                    "reason": f"owner heartbeat stale ({age}s > {stale_after_seconds}s)",
                }
                requeued.append(record)
                self.bus.emit("task.requeued", record, source="orchestrator")

            if changed:
                self._write_json(self.tasks_path, tasks)
            return requeued

    def reassign_stale_tasks_to_active_workers(
        self,
        source: str,
        stale_after_seconds: Optional[int] = None,
        include_blocked: bool = True,
    ) -> Dict[str, Any]:
        threshold = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            active_agents = self.list_agents(active_only=True, stale_after_seconds=threshold)
            active_names = [a.get("agent") for a in active_agents if isinstance(a.get("agent"), str)]
            # Do not reassign reported tasks: manager validation should run first.
            task_statuses = {"in_progress"}
            if include_blocked:
                task_statuses.add("blocked")

            reassigned: List[Dict[str, Any]] = []
            changed = False
            now = datetime.now(timezone.utc)

            for task in tasks:
                if task.get("status") not in task_statuses:
                    continue
                owner = str(task.get("owner", ""))
                if not owner:
                    continue

                owner_diag = self._team_member_connect_diagnostic(team_member=owner, stale_after_seconds=threshold)
                owner_active = bool(owner_diag.get("active"))
                if owner_active:
                    continue

                new_owner = self._pick_reassignment_owner(
                    task=task,
                    active_names=active_names,
                    tasks=tasks,
                )
                if not new_owner:
                    continue

                old_owner = owner
                task["owner"] = new_owner
                task["status"] = "assigned"
                task["updated_at"] = self._now()
                task["reassigned_from"] = old_owner
                task["reassigned_reason"] = f"owner stale (> {threshold}s)"
                task["degraded_comm"] = True
                task["degraded_comm_reason"] = "stale owner auto-reassigned"
                changed = True

                payload = {
                    "task_id": task.get("id"),
                    "from_owner": old_owner,
                    "to_owner": new_owner,
                    "reason": "owner_stale",
                    "threshold_seconds": threshold,
                    "owner_diagnostic": owner_diag,
                }
                reassigned.append(payload)
                self.bus.emit("task.reassigned_stale", payload, source=source)

            if changed:
                self._write_json(self.tasks_path, tasks)

            return {
                "reassigned_count": len(reassigned),
                "threshold_seconds": threshold,
                "reassigned": reassigned,
                "active_agents": active_names,
                "timestamp": now.isoformat(),
            }

    def validate_task(self, task_id: str, passed: bool, notes: str, source: str) -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            raise ValueError(f"leader_mismatch: source={source}, current_leader={manager}")
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            task = next((t for t in tasks if t["id"] == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")

            if passed:
                task["status"] = "done"
                self._close_bugs_for_task(task_id=task_id, note=notes)
                event = "validation.passed"
                payload = {"task_id": task_id, "owner": task["owner"], "notes": notes}
            else:
                task["status"] = "bug_open"
                bug = self._open_bug(
                    source_task=task_id,
                    owner=task["owner"],
                    severity="high",
                    repro_steps=notes,
                    expected="Task meets acceptance criteria",
                    actual="Validation failed",
                )
                event = "validation.failed"
                payload = {
                    "task_id": task_id,
                    "bug_id": bug["id"],
                    "owner": task["owner"],
                    "notes": notes,
                }

            task["updated_at"] = self._now()
            self._write_json(self.tasks_path, tasks)
        self.bus.emit(event, payload, source=source)
        return payload

    def list_bugs(self, status: Optional[str] = None, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        bugs = self._read_json(self.bugs_path)
        if status:
            bugs = [bug for bug in bugs if bug.get("status") == status]
        if owner:
            bugs = [bug for bug in bugs if bug.get("owner") == owner]
        return bugs

    def raise_blocker(
        self,
        task_id: str,
        agent: str,
        question: str,
        options: Optional[List[str]] = None,
        severity: str = "medium",
    ) -> Dict[str, Any]:
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            task = next((item for item in tasks if item["id"] == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            if task.get("owner") != agent:
                raise ValueError(f"Blocker agent '{agent}' does not match task owner '{task.get('owner')}'")

            task["status"] = "blocked"
            task["updated_at"] = self._now()
            self._write_json(self.tasks_path, tasks)

        blocker_id = f"BLK-{uuid.uuid4().hex[:8]}"
        blocker = {
            "id": blocker_id,
            "task_id": task_id,
            "agent": agent,
            "question": question,
            "options": options or [],
            "severity": severity,
            "status": "open",
            "created_at": self._now(),
        }

        with self._state_lock():
            blockers = self._read_json(self.blockers_path)
            blockers.append(blocker)
            self._write_json(self.blockers_path, blockers)
        self.bus.emit(
            "blocker.raised",
            {
                "blocker_id": blocker_id,
                "task_id": task_id,
                "agent": agent,
                "severity": severity,
                "question": question,
            },
            source=agent,
        )
        return blocker

    def list_blockers(self, status: Optional[str] = None, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        blockers = self._read_json(self.blockers_path)
        if status:
            blockers = [blk for blk in blockers if blk.get("status") == status]
        if agent:
            blockers = [blk for blk in blockers if blk.get("agent") == agent]
        return blockers

    def resolve_blocker(self, blocker_id: str, resolution: str, source: str) -> Dict[str, Any]:
        with self._state_lock():
            blockers = self._read_json(self.blockers_path)
            blocker = next((item for item in blockers if item["id"] == blocker_id), None)
            if blocker is None:
                raise ValueError(f"Blocker not found: {blocker_id}")
            if blocker.get("status") == "resolved":
                return blocker

            blocker["status"] = "resolved"
            blocker["resolution"] = resolution
            blocker["resolved_by"] = source
            blocker["resolved_at"] = self._now()
            self._write_json(self.blockers_path, blockers)

            tasks = self._read_json(self.tasks_path)
            task = next((item for item in tasks if item["id"] == blocker["task_id"]), None)
            if task is not None and task.get("status") == "blocked":
                owner = str(task.get("owner", ""))
                owner_diag = self._team_member_connect_diagnostic(
                    team_member=owner,
                    stale_after_seconds=self._heartbeat_timeout_seconds(),
                )
                owner_active = bool(owner_diag.get("active"))
                task["status"] = "in_progress" if owner_active else "assigned"
                if not owner_active:
                    # Avoid false "team_member is progressing" signal when owner appears offline.
                    task["degraded_comm"] = True
                    task["degraded_comm_reason"] = "blocker resolved while owner not active"
                    self.bus.emit(
                        "team_member.degraded_comm",
                        {
                            "task_id": task.get("id"),
                            "owner": owner,
                            "reason": "blocker resolved while owner offline/stale",
                            "diagnostic": owner_diag,
                        },
                        source="orchestrator",
                    )
                task["updated_at"] = self._now()
                self._write_json(self.tasks_path, tasks)

        self.bus.emit(
            "blocker.resolved",
            {"blocker_id": blocker_id, "task_id": blocker.get("task_id"), "resolution": resolution},
            source=source,
        )
        return blocker

    def publish_event(
        self,
        event_type: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
        audience: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        event_payload = dict(payload or {})
        if audience:
            event_payload["audience"] = audience
        return self.bus.emit(event_type=event_type, payload=event_payload, source=source)

    def manager_agent(self) -> str:
        roles = self._read_json(self.roles_path)
        if isinstance(roles, dict):
            leader = roles.get("leader")
            if isinstance(leader, str) and leader.strip():
                return leader
        return self.policy.manager()

    def get_roles(self) -> Dict[str, Any]:
        roles = self._read_json(self.roles_path)
        if not isinstance(roles, dict):
            roles = {}
        leader = roles.get("leader")
        if not isinstance(leader, str) or not leader.strip():
            leader = self.policy.manager()
        members = roles.get("team_members")
        if not isinstance(members, list):
            members = []
        normalized_members = sorted(
            {
                item.strip()
                for item in members
                if isinstance(item, str) and item.strip() and item.strip() != leader
            }
        )
        return {
            "leader": leader,
            "team_members": normalized_members,
            "default_leader": self.policy.manager(),
        }

    def set_role(self, agent: str, role: str, source: str) -> Dict[str, Any]:
        if not isinstance(agent, str) or not agent.strip():
            raise ValueError("agent must be a non-empty string")
        normalized_role = role.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized_role not in {"leader", "team_member"}:
            raise ValueError("role must be one of: leader, team_member")

        with self._state_lock():
            roles = self._read_json(self.roles_path)
            if not isinstance(roles, dict):
                roles = {}
            current = self.get_roles()
            current_leader = str(current["leader"])
            if source != current_leader:
                raise ValueError(f"leader_mismatch: source={source}, current_leader={current_leader}")
            leader = current["leader"]
            team_members = set(current["team_members"])
            target = agent.strip()

            if normalized_role == "leader":
                leader = target
                team_members.discard(target)
            else:
                if target == leader:
                    raise ValueError("current leader cannot be assigned as team_member")
                team_members.add(target)

            updated = {"leader": leader, "team_members": sorted(team_members)}
            self._write_json(self.roles_path, updated)
        self.bus.emit(
            "role.updated",
            {"agent": target, "role": normalized_role, "leader": leader, "team_members": sorted(team_members)},
            source=source,
        )
        return self.get_roles()

    def register_agent(self, agent: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._state_lock():
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                agents = {}
            entry = agents.get(agent, {})
            entry["agent"] = agent
            entry["status"] = "active"
            entry["metadata"] = metadata or entry.get("metadata", {})
            entry["last_seen"] = self._now()
            agents[agent] = entry
            self._write_json(self.agents_path, agents)
        self.bus.emit("agent.registered", {"agent": agent, "metadata": entry["metadata"]}, source=agent)
        return entry

    def heartbeat(self, agent: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._state_lock():
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                agents = {}
            entry = agents.get(agent, {"agent": agent, "metadata": {}})
            entry["status"] = "active"
            if metadata:
                merged = dict(entry.get("metadata", {}))
                merged.update(metadata)
                entry["metadata"] = merged
            entry["last_seen"] = self._now()
            agents[agent] = entry
            self._write_json(self.agents_path, agents)
        self.bus.emit("agent.heartbeat", {"agent": agent}, source=agent)
        return entry

    def connect_to_leader(
        self,
        agent: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "idle",
        announce: bool = True,
        source: Optional[str] = None,
        project_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        manager = self.manager_agent()
        details = dict(metadata or {})
        details.setdefault("role", "team_member")
        details["status"] = status
        override_applied = False
        override_path = str(project_override).strip() if project_override is not None else ""
        if override_path:
            if source != manager:
                return {
                    "connected": False,
                    "agent": agent,
                    "manager": manager,
                    "entry": None,
                    "identity": {
                        "agent_id": agent,
                        "verified": False,
                        "same_project": False,
                        "reason": "project_override_requires_manager_source",
                    },
                    "verified": False,
                    "reason": "project_override_requires_manager_source",
                    "auto_claimed_task": None,
                    "next": [
                        f"orchestrator_set_agent_project_context(agent={agent}, project_root=<path>, source={manager})",
                        f"orchestrator_connect_to_leader(agent={agent})",
                    ],
                }
            details["project_root"] = override_path
            # Keep context coherent for same_project checks.
            details["cwd"] = override_path
            details["project_override_by"] = manager
            details["project_override_at"] = self._now()
            override_applied = True

        self.register_agent(agent=agent, metadata=details)
        entry = self.heartbeat(agent=agent, metadata={"status": status})
        effective_source = source if isinstance(source, str) and source.strip() else agent

        identity = self._identity_snapshot(entry=entry, stale_after_seconds=self._heartbeat_timeout_seconds())
        verification = {
            "verified": bool(identity.get("verified")),
            "same_project": bool(identity.get("same_project")),
            "reason": identity.get("reason"),
        }
        manager_override_connect = override_applied and effective_source == manager and agent != manager
        if effective_source != agent and not manager_override_connect:
            verification["verified"] = False
            verification["reason"] = "source_agent_mismatch"
        requested_role = str(details.get("role", "team_member")).strip().lower()
        if agent == manager and requested_role != "manager":
            verification["verified"] = False
            verification["reason"] = "manager_role_mismatch"
        if agent != manager and requested_role == "manager":
            verification["verified"] = False
            verification["reason"] = "non_manager_declared_manager_role"
        connected = bool(verification.get("verified")) and bool(verification.get("same_project"))

        event_payload = {
            "agent": agent,
            "status": status,
            "manager": manager,
            "next_action": "poll_events_then_claim_once",
            "verified": verification.get("verified"),
            "reason": verification.get("reason"),
        }
        if announce:
            self.publish_event(
                event_type="team_member.connected",
                source=agent,
                payload=event_payload,
                audience=[manager],
            )

        # Team members auto-claim on connect; manager/leader should never auto-claim implementation work.
        role = str((metadata or {}).get("role", details.get("role", "team_member"))).strip().lower()
        is_manager_connect = agent == manager or role == "manager"
        auto_claimed = self.claim_next_task(owner=agent) if connected and not is_manager_connect else None

        return {
            "connected": connected,
            "agent": agent,
            "manager": manager,
            "entry": entry,
            "identity": identity,
            "verified": verification.get("verified"),
            "reason": verification.get("reason"),
            "auto_claimed_task": auto_claimed,
            "next": [
                f"orchestrator_poll_events(agent={agent}, timeout_ms=120000)",
                f"orchestrator_claim_next_task(agent={agent})",
            ],
            "project_override_applied": override_applied,
        }

    def set_agent_project_context(
        self,
        agent: str,
        project_root: str,
        source: str,
        cwd: Optional[str] = None,
    ) -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            raise ValueError(f"leader_mismatch: source={source}, current_leader={manager}")
        normalized_root = str(project_root).strip()
        if not normalized_root:
            raise ValueError("project_root must be non-empty")
        normalized_cwd = str(cwd).strip() if cwd is not None else normalized_root
        with self._state_lock():
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                agents = {}
            entry = agents.get(agent)
            if not isinstance(entry, dict):
                entry = {"agent": agent, "metadata": {}}
            metadata = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
            metadata["project_root"] = normalized_root
            metadata["cwd"] = normalized_cwd
            metadata["project_override_by"] = source
            metadata["project_override_at"] = self._now()
            entry["metadata"] = metadata
            entry["status"] = "active"
            entry["last_seen"] = self._now()
            agents[agent] = entry
            self._write_json(self.agents_path, agents)
            stale_after = self._heartbeat_timeout_seconds()
            identity = self._identity_snapshot(entry=entry, stale_after_seconds=stale_after)
        self.bus.emit(
            "manager.project_context_override",
            {"agent": agent, "project_root": normalized_root, "cwd": normalized_cwd, "source": source},
            source=source,
        )
        return {
            "ok": True,
            "agent": agent,
            "project_root": normalized_root,
            "cwd": normalized_cwd,
            "identity": identity,
        }

    def list_agents(
        self,
        active_only: bool = False,
        stale_after_seconds: Optional[int] = None,
        emit_stale_notices: bool = False,
    ) -> List[Dict[str, Any]]:
        stale_after = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            return []

        now = datetime.now(timezone.utc)
        results: List[Dict[str, Any]] = []
        tasks = self.list_tasks()
        stale_notices = self._read_json(self.stale_notices_path)
        if not isinstance(stale_notices, dict):
            stale_notices = {}
        stale_changed = False

        for _, entry in agents.items():
            item = dict(entry)
            last_seen_raw = item.get("last_seen")
            if last_seen_raw:
                try:
                    last_seen = datetime.fromisoformat(last_seen_raw)
                    age = int((now - last_seen).total_seconds())
                except Exception:
                    age = stale_after + 1
            else:
                age = stale_after + 1

            computed_status = "active" if age <= stale_after else "offline"
            identity = self._identity_snapshot(entry=item, stale_after_seconds=stale_after)
            if not bool(identity.get("verified")) or not bool(identity.get("same_project")):
                computed_status = "offline"
            item["status"] = computed_status
            item["age_seconds"] = max(0, age)
            item.update(identity)
            if computed_status == "active":
                if item.get("agent") in stale_notices:
                    del stale_notices[item["agent"]]
                    stale_changed = True
            else:
                if emit_stale_notices and self._emit_stale_notice_if_due(
                    agent=item.get("agent", ""),
                    age_seconds=max(0, age),
                    stale_after_seconds=stale_after,
                    stale_notices=stale_notices,
                    now=now,
                    known_agents=list(agents.keys()),
                ):
                    stale_changed = True
            if active_only and item["status"] != "active":
                continue
            item["task_counts"] = {
                "assigned": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "assigned"
                ),
                "in_progress": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "in_progress"
                ),
                "blocked": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "blocked"
                ),
                "done": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "done"
                ),
            }
            results.append(item)

        if stale_changed:
            self._write_json(self.stale_notices_path, stale_notices)
        results.sort(key=lambda x: x.get("agent", ""))
        return results

    def discover_agents(self, active_only: bool = False, stale_after_seconds: Optional[int] = None) -> Dict[str, Any]:
        registered = self.list_agents(active_only=active_only, stale_after_seconds=stale_after_seconds)
        registered_names = {entry.get("agent") for entry in registered}

        inferred_names: set[str] = set()
        events = list(self.bus.iter_events())
        for event in events:
            source = event.get("source")
            if source and source not in {"orchestrator", "governance"}:
                inferred_names.add(source)
            payload = event.get("payload") or {}
            audience = payload.get("audience")
            if isinstance(audience, list):
                for item in audience:
                    if isinstance(item, str):
                        inferred_names.add(item)

        for task in self.list_tasks():
            owner = task.get("owner")
            if isinstance(owner, str):
                inferred_names.add(owner)

        inferred_only = []
        for name in sorted(inferred_names):
            if name in registered_names:
                continue
            inferred_only.append(
                {
                    "agent": name,
                    "status": "unknown",
                    "metadata": {},
                    "inferred": True,
                    "inferred_from": ["events", "tasks"],
                    "agent_id": name,
                    "client": None,
                    "model": None,
                    "project_root": None,
                    "cwd": None,
                    "permissions_mode": None,
                    "sandbox_mode": None,
                    "session_id": None,
                    "connection_id": None,
                    "server_version": None,
                    "verification_source": "inferred_only",
                    "verified": False,
                    "reason": "not_registered",
                    "same_project": False,
                    "last_seen": None,
                    "age_seconds": None,
                }
            )

        all_agents = list(registered) + inferred_only
        all_agents.sort(key=lambda x: x.get("agent", ""))
        return {
            "registered_count": len(registered),
            "inferred_only_count": len(inferred_only),
            "agents": all_agents,
        }

    def get_agent_cursor(self, agent: str) -> int:
        cursors = self._read_json(self.cursors_path)
        if not isinstance(cursors, dict):
            cursors = {}
            self._write_json(self.cursors_path, cursors)
        return int(cursors.get(agent, 0))

    def poll_events(
        self,
        agent: str,
        cursor: Optional[int] = None,
        limit: int = 50,
        timeout_ms: int = 0,
        auto_advance: bool = True,
    ) -> Dict[str, Any]:
        # Long-poll calls are the normal team_member loop heartbeat in practice.
        self._assert_agent_operational(agent)
        self._refresh_agent_presence(agent)
        start = self.get_agent_cursor(agent) if cursor is None else max(0, int(cursor))
        self.bus.wait_for_event_index(start=start, timeout_ms=timeout_ms)
        filtered: List[Dict[str, Any]] = []
        current_index = start

        for idx, event in self.bus.iter_events_from(start=start):
            payload = event.get("payload", {})
            audience = payload.get("audience")
            if audience and agent not in audience and "*" not in audience:
                current_index = idx + 1
                continue

            enriched = dict(event)
            enriched["offset"] = idx
            filtered.append(enriched)
            current_index = idx + 1
            if len(filtered) >= limit:
                break

        next_cursor = current_index
        if auto_advance:
            self._set_agent_cursor(agent, next_cursor)

        return {
            "agent": agent,
            "cursor": start,
            "next_cursor": next_cursor,
            "events": filtered,
        }

    def ack_event(self, agent: str, event_id: str) -> Dict[str, Any]:
        self._refresh_agent_presence(agent)
        with self._state_lock():
            acks = self._read_json(self.acks_path)
            if not isinstance(acks, dict):
                acks = {}
                self._write_json(self.acks_path, acks)
            acked = acks.get(agent, [])
            if event_id not in acked:
                acked.append(event_id)
                acks[agent] = acked
                self._write_json(self.acks_path, acks)

        self.bus.emit(
            "event.acked",
            {"agent": agent, "event_id": event_id},
            source=agent,
        )
        return {"agent": agent, "event_id": event_id, "acked": True}

    def _set_agent_cursor(self, agent: str, cursor: int) -> None:
        with self._state_lock():
            cursors = self._read_json(self.cursors_path)
            if not isinstance(cursors, dict):
                cursors = {}
            cursors[agent] = max(0, int(cursor))
            self._write_json(self.cursors_path, cursors)

    def _close_bugs_for_task(self, task_id: str, note: str) -> None:
        bugs = self._read_json(self.bugs_path)
        changed = False
        for bug in bugs:
            if bug.get("source_task") != task_id:
                continue
            if bug.get("status") == "closed":
                continue
            bug["status"] = "closed"
            bug["closed_at"] = self._now()
            bug["resolution_note"] = note
            changed = True
            self.bus.emit(
                "bug.closed",
                {"bug_id": bug.get("id"), "source_task": task_id, "note": note},
                source=self.manager_agent(),
            )
        if changed:
            self._write_json(self.bugs_path, bugs)

    def record_architecture_decision(
        self,
        topic: str,
        options: List[str],
        votes: Dict[str, str],
        rationale: Dict[str, str],
    ) -> Path:
        members = self.policy.voters()
        missing_votes = [member for member in members if member not in votes]
        if missing_votes:
            raise ValueError(f"Missing votes for: {', '.join(missing_votes)}")

        counts: Dict[str, int] = {option: 0 for option in options}
        for _, voted_option in votes.items():
            if voted_option not in counts:
                raise ValueError(f"Vote contains unknown option: {voted_option}")
            counts[voted_option] += 1

        winner = max(counts, key=counts.get)
        decision_id = f"ADR-{uuid.uuid4().hex[:6]}"
        path = self.decisions_dir / f"{decision_id}.md"

        lines = [
            f"# {decision_id}: {topic}",
            "",
            f"- Mode: {self.policy.architecture_mode()}",
            f"- Members: {', '.join(members)}",
            f"- Winner: {winner}",
            "",
            "## Options",
        ]
        lines.extend([f"- {opt}" for opt in options])
        lines.append("")
        lines.append("## Votes")
        lines.extend([f"- {member}: {votes[member]}" for member in members])
        lines.append("")
        lines.append("## Rationale")
        lines.extend([f"- {member}: {rationale.get(member, 'No rationale provided')}" for member in members])
        lines.append("")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.bus.emit(
            "architecture.decided",
            {
                "decision_id": decision_id,
                "topic": topic,
                "winner": winner,
                "votes": votes,
            },
            source="governance",
        )
        return path

    def _open_bug(
        self,
        source_task: str,
        owner: str,
        severity: str,
        repro_steps: str,
        expected: str,
        actual: str,
    ) -> Dict[str, Any]:
        bugs = self._read_json(self.bugs_path)
        bug_id = f"BUG-{uuid.uuid4().hex[:8]}"
        bug = {
            "id": bug_id,
            "source_task": source_task,
            "owner": owner,
            "severity": severity,
            "repro_steps": repro_steps,
            "expected": expected,
            "actual": actual,
            "status": "open",
            "created_at": self._now(),
        }
        bugs.append(bug)
        self._write_json(self.bugs_path, bugs)
        return bug

    def _validate_report_payload(self, report: Dict[str, Any]) -> None:
        if not isinstance(report.get("commit_sha"), str) or not report.get("commit_sha", "").strip():
            raise ValueError("commit_sha must be a non-empty string")

        summary = report.get("test_summary")
        if not isinstance(summary, dict):
            raise ValueError("test_summary must be an object")

        for key in ("command", "passed", "failed"):
            if key not in summary:
                raise ValueError(f"test_summary missing required field: {key}")

        command = summary.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("test_summary.command must be a non-empty string")

        passed = summary.get("passed")
        failed = summary.get("failed")
        if not isinstance(passed, int) or passed < 0:
            raise ValueError("test_summary.passed must be a non-negative integer")
        if not isinstance(failed, int) or failed < 0:
            raise ValueError("test_summary.failed must be a non-negative integer")

    def _task_fingerprint(self, title: str, workstream: str, owner: str) -> str:
        norm_title = re.sub(r"\s+", " ", title.strip().lower())
        return f"{owner.strip().lower()}::{workstream.strip().lower()}::{norm_title}"

    def _find_duplicate_open_task(
        self,
        tasks: List[Dict[str, Any]],
        title: str,
        workstream: str,
        owner: str,
    ) -> Optional[Dict[str, Any]]:
        open_statuses = {"assigned", "in_progress", "reported", "bug_open", "blocked"}
        candidate_key = self._task_fingerprint(title=title, workstream=workstream, owner=owner)
        for task in tasks:
            if task.get("status") not in open_statuses:
                continue
            existing_key = self._task_fingerprint(
                title=str(task.get("title", "")),
                workstream=str(task.get("workstream", "")),
                owner=str(task.get("owner", "")),
            )
            if existing_key == candidate_key:
                return task
        return None

    def _refresh_agent_presence(self, agent: str) -> None:
        """Update last_seen/status without emitting extra heartbeat events."""
        if not isinstance(agent, str) or not agent.strip():
            return
        with self._state_lock():
            self._refresh_agent_presence_unlocked(agent)

    def _refresh_agent_presence_unlocked(self, agent: str) -> None:
        """Update last_seen/status without lock acquisition (caller must hold _state_lock)."""
        if not isinstance(agent, str) or not agent.strip():
            return
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            agents = {}
        entry = agents.get(agent, {"agent": agent, "metadata": {}})
        entry["status"] = "active"
        entry["last_seen"] = self._now()
        agents[agent] = entry
        self._write_json(self.agents_path, agents)

    def _heartbeat_timeout_seconds(self) -> int:
        minutes = self.policy.triggers.get("heartbeat_timeout_minutes", 10)
        try:
            value = int(minutes)
        except Exception:
            value = 10
        return max(60, value * 60)

    def _team_member_connect_diagnostic(self, team_member: str, stale_after_seconds: int) -> Dict[str, Any]:
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            agents = {}
        entry = agents.get(team_member, {})
        now = datetime.now(timezone.utc)

        last_seen = entry.get("last_seen")
        age = self._age_seconds(str(last_seen), now=now) if last_seen else None
        active = age is not None and age <= stale_after_seconds

        open_statuses = {"assigned", "in_progress", "reported", "bug_open", "blocked"}
        owned_open_tasks = [t for t in self.list_tasks() if t.get("owner") == team_member and t.get("status") in open_statuses]
        latest_task_update_age: Optional[int] = None
        for task in owned_open_tasks:
            updated_at = task.get("updated_at")
            if not updated_at:
                continue
            task_age = self._age_seconds(str(updated_at), now=now)
            if task_age is None:
                continue
            if latest_task_update_age is None or task_age < latest_task_update_age:
                latest_task_update_age = task_age

        reason = "active" if active else "no_recent_heartbeat"
        if not entry:
            reason = "not_registered"

        identity = self._identity_snapshot(entry=entry, stale_after_seconds=stale_after_seconds)
        if not identity.get("verified"):
            active = False
            reason = str(identity.get("reason", reason))
        return {
            "registered": bool(entry),
            "active": bool(active),
            "status": entry.get("status", "unknown"),
            "last_seen": last_seen,
            "age_seconds": age,
            "reason": reason,
            "owned_open_tasks": len(owned_open_tasks),
            "latest_open_task_update_age_seconds": latest_task_update_age,
            "identity": identity,
        }

    def _identity_snapshot(self, entry: Dict[str, Any], stale_after_seconds: int) -> Dict[str, Any]:
        metadata = entry.get("metadata", {}) if isinstance(entry, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        now = datetime.now(timezone.utc)
        last_seen = entry.get("last_seen")
        age = self._age_seconds(str(last_seen), now=now) if last_seen else None

        project_root = str(metadata.get("project_root", ""))
        cwd = str(metadata.get("cwd", ""))
        project_root_resolved = self._safe_resolve(project_root) if project_root else None
        cwd_resolved = self._safe_resolve(cwd) if cwd else None
        same_project = False
        if project_root_resolved is not None and cwd_resolved is not None:
            same_project = project_root_resolved == self.root and self._path_within_project(cwd_resolved)
        elif project_root_resolved is not None:
            same_project = project_root_resolved == self.root
        elif cwd_resolved is not None:
            same_project = self._path_within_project(cwd_resolved)

        verification = self._verification_for_entry(entry=entry, stale_after_seconds=stale_after_seconds)
        verification["same_project"] = same_project
        if verification.get("verified") and not same_project:
            verification["verified"] = False
            verification["reason"] = "project_mismatch"

        return {
            "agent_id": entry.get("agent"),
            "client": metadata.get("client"),
            "model": metadata.get("model"),
            "project_root": project_root or cwd,
            "cwd": cwd,
            "permissions_mode": metadata.get("permissions_mode"),
            "sandbox_mode": metadata.get("sandbox_mode"),
            "session_id": metadata.get("session_id"),
            "connection_id": metadata.get("connection_id"),
            "server_version": metadata.get("server_version"),
            "verification_source": metadata.get("verification_source"),
            "verified": bool(verification.get("verified")),
            "reason": verification.get("reason"),
            "same_project": same_project,
            "last_seen": last_seen,
            "age_seconds": age,
        }

    def _verification_for_entry(self, entry: Dict[str, Any], stale_after_seconds: int) -> Dict[str, Any]:
        metadata = entry.get("metadata", {}) if isinstance(entry, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        required = [
            "client",
            "model",
            "cwd",
            "permissions_mode",
            "sandbox_mode",
            "session_id",
            "connection_id",
            "server_version",
            "verification_source",
        ]
        missing = [key for key in required if not str(metadata.get(key, "")).strip()]
        last_seen = entry.get("last_seen")
        age = self._age_seconds(str(last_seen)) if last_seen else None
        if missing:
            return {"verified": False, "reason": f"missing_identity_fields:{','.join(missing)}"}
        if age is None or age > stale_after_seconds:
            return {"verified": False, "reason": "no_recent_heartbeat"}
        return {"verified": True, "reason": "verified_identity"}

    def _safe_resolve(self, raw_path: str) -> Optional[Path]:
        try:
            return Path(raw_path).expanduser().resolve()
        except Exception:
            return None

    def _path_within_project(self, path: Path) -> bool:
        try:
            return path == self.root or self.root in path.parents
        except Exception:
            return False

    def _emit_stale_notice_if_due(
        self,
        agent: str,
        age_seconds: int,
        stale_after_seconds: int,
        stale_notices: Dict[str, Any],
        now: datetime,
        known_agents: List[str],
    ) -> bool:
        if not agent:
            return False

        cooldown_seconds = max(60, stale_after_seconds)
        last_notice_iso = stale_notices.get(agent)
        if last_notice_iso:
            try:
                last_notice = datetime.fromisoformat(str(last_notice_iso))
                elapsed = int((now - last_notice).total_seconds())
                if elapsed < cooldown_seconds:
                    return False
            except Exception:
                pass

        manager = self.manager_agent()
        audience = [agent, manager]
        if agent == manager:
            team_members = [a for a in known_agents if a and a != manager]
            audience = sorted(set(team_members + [manager]))

        self.bus.emit(
            "agent.stale_reconnect_required",
            {
                "agent": agent,
                "age_seconds": age_seconds,
                "stale_after_seconds": stale_after_seconds,
                "action": "rerun handshake",
                "team_member_action": "run 'connect to leader'",
                "manager_action": "run orchestrator_connect_team_members",
                "audience": audience,
            },
            source="orchestrator",
        )
        stale_notices[agent] = self._now()
        return True

    def _pick_reassignment_owner(
        self,
        task: Dict[str, Any],
        active_names: List[str],
        tasks: List[Dict[str, Any]],
    ) -> Optional[str]:
        owner = str(task.get("owner", ""))
        candidates = [name for name in active_names if name and name != owner]
        if not candidates:
            return None

        # Prefer policy-routed owner for this workstream if active.
        preferred = self.policy.task_owner_for(str(task.get("workstream", "default")))
        if preferred in candidates:
            return preferred

        def load(agent: str) -> int:
            return sum(
                1
                for t in tasks
                if t.get("owner") == agent and t.get("status") in {"assigned", "in_progress", "reported", "bug_open", "blocked"}
            )

        return sorted(candidates, key=load)[0]

    def _age_seconds(self, iso_timestamp: str, now: Optional[datetime] = None) -> Optional[int]:
        try:
            ts = datetime.fromisoformat(iso_timestamp)
            current = now or datetime.now(timezone.utc)
            return int((current - ts).total_seconds())
        except Exception:
            return None

    def _agent_is_operational(
        self,
        agent: str,
        stale_after_seconds: Optional[int] = None,
    ) -> bool:
        if not isinstance(agent, str) or not agent.strip():
            return False
        with self._state_lock():
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                return False
            entry = agents.get(agent)
            if not isinstance(entry, dict):
                return False
            stale_after = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
            identity = self._identity_snapshot(entry=entry, stale_after_seconds=stale_after)
            # Operational guard focuses on identity + project isolation, not recency.
            # This allows agents to recover after downtime without manual re-registration
            # while still blocking cross-project or missing-identity access.
            metadata = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
            required = [
                "client",
                "model",
                "cwd",
                "permissions_mode",
                "sandbox_mode",
                "session_id",
                "connection_id",
                "server_version",
                "verification_source",
            ]
            identity_complete = all(str(metadata.get(key, "")).strip() for key in required)
            return bool(identity_complete) and bool(identity.get("same_project"))

    def _assert_agent_operational(self, agent: str) -> None:
        if not self._agent_is_operational(agent):
            raise ValueError(f"agent_not_operational_or_wrong_project: {agent}")

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
