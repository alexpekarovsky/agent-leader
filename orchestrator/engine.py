from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestrator.bus import EventBus
from orchestrator.policy import Policy


@dataclass
class Orchestrator:
    root: Path
    policy: Policy

    def __post_init__(self) -> None:
        self.bus = EventBus(self.root / "bus")
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_path = self.state_dir / "tasks.json"
        self.bugs_path = self.state_dir / "bugs.json"
        self.blockers_path = self.state_dir / "blockers.json"
        self.cursors_path = self.state_dir / "event_cursors.json"
        self.acks_path = self.state_dir / "event_acks.json"
        self.agents_path = self.state_dir / "agents.json"
        self.decisions_dir = self.root / "decisions"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)

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
        self.bus.emit(
            "orchestrator.bootstrapped",
            {"policy": self.policy.name, "manager": self.policy.manager()},
            source="orchestrator",
        )

    def connect_workers(
        self,
        source: str,
        workers: List[str],
        timeout_seconds: int = 60,
        poll_interval_seconds: int = 2,
        stale_after_seconds: int = 300,
    ) -> Dict[str, Any]:
        requested = sorted({w.strip() for w in workers if isinstance(w, str) and w.strip()})
        if not requested:
            raise ValueError("workers must contain at least one non-empty agent id")

        started_at = time.time()
        deadline = started_at + max(1, int(timeout_seconds))

        # One manager signal that workers should register + heartbeat now.
        self.publish_event(
            event_type="manager.connect_workers",
            source=source,
            payload={"workers": requested, "timeout_seconds": int(timeout_seconds)},
            audience=requested,
        )

        connected: List[str] = []
        while time.time() < deadline:
            agents = self.list_agents(active_only=False, stale_after_seconds=stale_after_seconds)
            active = {
                item.get("agent")
                for item in agents
                if item.get("agent") in requested and item.get("status") == "active"
            }
            connected = sorted(active)
            if len(connected) == len(requested):
                break
            time.sleep(max(1, int(poll_interval_seconds)))

        missing = [worker for worker in requested if worker not in set(connected)]
        status = "connected" if not missing else "timeout"

        self.publish_event(
            event_type="manager.connect_workers.result",
            source=source,
            payload={"status": status, "connected": connected, "missing": missing},
            audience=requested,
        )

        return {
            "status": status,
            "requested": requested,
            "connected": connected,
            "missing": missing,
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
        tasks = self._read_json(self.tasks_path)
        task_id = f"TASK-{uuid.uuid4().hex[:8]}"
        resolved_owner = owner or self.policy.task_owner_for(workstream)
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
            source=self.policy.manager(),
        )
        return task

    def list_tasks(self) -> List[Dict[str, Any]]:
        return self._read_json(self.tasks_path)

    def list_tasks_for_owner(self, owner: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = [task for task in self.list_tasks() if task.get("owner") == owner]
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return tasks

    def claim_next_task(self, owner: str) -> Optional[Dict[str, Any]]:
        tasks = self._read_json(self.tasks_path)
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

    def set_task_status(self, task_id: str, status: str, source: str, note: str = "") -> Dict[str, Any]:
        tasks = self._read_json(self.tasks_path)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

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

        task_id = report["task_id"]
        tasks = self._read_json(self.tasks_path)
        task = next((item for item in tasks if item["id"] == task_id), None)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if task.get("owner") != report["agent"]:
            raise ValueError(
                f"Report agent '{report['agent']}' does not match task owner '{task.get('owner')}'"
            )

        report_path = self.bus.reports_dir / f"{task_id}.json"
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

        task["status"] = "reported"
        task["updated_at"] = self._now()
        self._write_json(self.tasks_path, tasks)

        self.bus.emit(
            "task.reported",
            {"task_id": task_id, "agent": report["agent"], "status": report["status"]},
            source=report["agent"],
        )
        return report

    def requeue_stale_in_progress_tasks(self, stale_after_seconds: int = 1800) -> List[Dict[str, Any]]:
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

    def validate_task(self, task_id: str, passed: bool, notes: str) -> Dict[str, Any]:
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
        self.bus.emit(event, payload, source=self.policy.manager())
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
            task["status"] = "in_progress"
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

    def register_agent(self, agent: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        details = dict(metadata or {})
        details.setdefault("role", "worker")
        details["status"] = status

        self.register_agent(agent=agent, metadata=details)
        entry = self.heartbeat(agent=agent, metadata={"status": status})

        manager = self.policy.manager()
        event_payload = {
            "agent": agent,
            "status": status,
            "manager": manager,
            "next_action": "poll_events_then_claim_once",
        }
        if announce:
            self.publish_event(
                event_type="worker.connected",
                source=agent,
                payload=event_payload,
                audience=[manager],
            )

        return {
            "connected": True,
            "agent": agent,
            "manager": manager,
            "entry": entry,
            "next": [
                f"orchestrator_poll_events(agent={agent}, timeout_ms=120000)",
                f"orchestrator_claim_next_task(agent={agent})",
            ],
        }

    def list_agents(self, active_only: bool = False, stale_after_seconds: int = 300) -> List[Dict[str, Any]]:
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            return []

        now = datetime.now(timezone.utc)
        results: List[Dict[str, Any]] = []
        changed = False
        tasks = self.list_tasks()

        for _, entry in agents.items():
            item = dict(entry)
            last_seen_raw = item.get("last_seen")
            if last_seen_raw:
                try:
                    last_seen = datetime.fromisoformat(last_seen_raw)
                    age = int((now - last_seen).total_seconds())
                except Exception:
                    age = stale_after_seconds + 1
            else:
                age = stale_after_seconds + 1

            computed_status = "active" if age <= stale_after_seconds else "offline"
            if item.get("status") != computed_status:
                item["status"] = computed_status
                agents[item["agent"]] = item
                changed = True
            item["age_seconds"] = max(0, age)
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

        if changed:
            self._write_json(self.agents_path, agents)
        results.sort(key=lambda x: x.get("agent", ""))
        return results

    def discover_agents(self, active_only: bool = False, stale_after_seconds: int = 300) -> Dict[str, Any]:
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
        events = list(self.bus.poll_events(timeout_ms=timeout_ms))
        start = self.get_agent_cursor(agent) if cursor is None else max(0, int(cursor))
        filtered: List[Dict[str, Any]] = []
        current_index = start

        for idx, event in enumerate(events[start:], start=start):
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
                source=self.policy.manager(),
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

    def _age_seconds(self, iso_timestamp: str, now: Optional[datetime] = None) -> Optional[int]:
        try:
            ts = datetime.fromisoformat(iso_timestamp)
            current = now or datetime.now(timezone.utc)
            return int((current - ts).total_seconds())
        except Exception:
            return None

    @staticmethod
    def _read_json(path: Path) -> Any:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=2)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
