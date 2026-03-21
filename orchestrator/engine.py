from __future__ import annotations

import copy
import json
import logging
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

logger = logging.getLogger("orchestrator.engine")

from orchestrator.bus import EventBus
from orchestrator.policy import Policy
from orchestrator.quality_gates import QualityGateOutcome, run_quality_gates
from orchestrator.self_review import SelfReviewConfig
from orchestrator.github_ci import normalize_github_ci_result, build_github_issue_payload, post_github_issue
from orchestrator import pr_stack as _pr_stack
from orchestrator.migration import migrate_state as _migrate_state

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None


_META_BLOCKER_PATTERNS = (
    "watchdog",
    "project_mismatch",
    "wrong project scope",
    "stale",
    "task stale",
    "marked this task stale",
    "targets .*, not ",
    "cannot work on tasks outside my project",
)

TASK_TYPES = {"standard", "comprehend_project"}


@dataclass
class Orchestrator:
    root: Path
    policy: Policy

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.bus = EventBus(self.root / "bus")
        # In-memory per-agent cooldown tracker for empty claim_next_task calls.
        # Maps agent name -> (monotonic_ts, tasks_file_mtime) at last empty claim.
        self._claim_cooldowns: Dict[str, tuple] = {}
        # In-memory mtime-based JSON file cache.
        # Maps str(path) -> (mtime_ns: int, parsed_data: Any).
        self._json_cache: Dict[str, tuple] = {}
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_path = self.state_dir / "tasks.json"
        self.bugs_path = self.state_dir / "bugs.json"
        self.blockers_path = self.state_dir / "blockers.json"
        self.cursors_path = self.state_dir / "event_cursors.json"
        self.acks_path = self.state_dir / "event_acks.json"
        self.agents_path = self.state_dir / "agents.json"
        self.agent_instances_path = self.state_dir / "agent_instances.json"
        self.stale_notices_path = self.state_dir / "stale_notices.json"
        self.claim_overrides_path = self.state_dir / "claim_overrides.json"
        self.report_retry_queue_path = self.state_dir / "report_retry_queue.json"
        self.roles_path = self.state_dir / "roles.json"
        self.consults_path = self.state_dir / "consults.json"
        self.pr_stacks_path = self.state_dir / "pr_stacks.json"
        self.decisions_dir = self.root / "decisions"
        self.decisions_dir.mkdir(parents=True, exist_ok=True)
        self.state_lock_path = self.state_dir / ".state.lock"
        self.github_repo_config_path = self.state_dir / "github_repo_config.json"
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
        if not self.agent_instances_path.exists():
            self.agent_instances_path.write_text("{}\n", encoding="utf-8")
        if not self.stale_notices_path.exists():
            self.stale_notices_path.write_text("{}\n", encoding="utf-8")
        if not self.claim_overrides_path.exists():
            self.claim_overrides_path.write_text("{}\n", encoding="utf-8")
        if not self.report_retry_queue_path.exists():
            self.report_retry_queue_path.write_text("[]\n", encoding="utf-8")
        if not self.consults_path.exists():
            self.consults_path.write_text("[]\n", encoding="utf-8")
        if not self.pr_stacks_path.exists():
            self.pr_stacks_path.write_text("[]\n", encoding="utf-8")
        if not self.github_repo_config_path.exists():
            self.github_repo_config_path.write_text("{}\n", encoding="utf-8")
        if not self.roles_path.exists():
            self.roles_path.write_text(
                json.dumps(
                    {
                        "leader": self.policy.manager(),
                        "leader_instance_id": f"{self.policy.manager()}#default",
                        "team_members": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        # Migrate legacy (v0) state files to current schema version.
        try:
            _migrate_state(self.state_dir, self.bus.root)
        except Exception as exc:
            print(f"WARNING: state migration failed: {exc}", file=sys.stderr, flush=True)

        self.bus.emit(
            "orchestrator.bootstrapped",
            {"policy": self.policy.name, "manager": self.policy.manager()},
            source="orchestrator",
        )
        # Heal common collection-file corruption (e.g. {} persisted instead of []).
        self._ensure_list_file(self.bugs_path)
        self._ensure_list_file(self.blockers_path)

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
                    and (bool(item.get("same_project")) or self._allow_cross_project_agents())
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
        risk: Optional[str] = None,
        test_plan: Optional[str] = None,
        doc_impact: Optional[str] = None,
        project_root: Optional[str] = None,
        project_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        task_type: Optional[str] = None,
        parent_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_task_type = self._normalize_task_type(task_type)
        delivery_profile = self._normalize_task_delivery_profile(
            risk=risk,
            test_plan=test_plan,
            doc_impact=doc_impact,
        )
        normalized_root = str(project_root or str(self.root)).strip() or str(self.root)
        normalized_name = str(project_name or Path(normalized_root).name or self.root.name).strip() or self.root.name
        normalized_team_id = str(team_id or "").strip().lower()
        normalized_parent = str(parent_task_id or "").strip() or None
        task_tags = self._normalize_task_tags(
            tags=tags,
            project_name=normalized_name,
            workstream=workstream,
            team_id=normalized_team_id or None,
        )
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            if normalized_parent:
                parent = next((t for t in tasks if t["id"] == normalized_parent), None)
                if parent is None:
                    raise ValueError(f"Parent task not found: {normalized_parent}")
            task_id = f"TASK-{uuid.uuid4().hex[:8]}"
            resolved_owner = owner or self.policy.task_owner_for(workstream)
            duplicate = self._find_duplicate_open_task(
                tasks=tasks,
                title=title,
                workstream=workstream,
                owner=resolved_owner,
            )
            if duplicate is not None:
                logger.info("task.deduplicated title=%s existing_id=%s owner=%s", title[:60], duplicate.get("id"), resolved_owner)
                echoed = dict(duplicate)
                echoed["deduplicated"] = True
                echoed["dedupe_reason"] = "matching open task already exists"
                return echoed

            task = {
                "id": task_id,
                "title": title,
                "description": description,
                "task_type": normalized_task_type,
                "workstream": workstream,
                "owner": resolved_owner,
                "project_root": normalized_root,
                "project_name": normalized_name,
                "team_id": normalized_team_id or None,
                "parent_task_id": normalized_parent,
                "tags": task_tags,
                "status": "assigned",
                "acceptance_criteria": acceptance_criteria,
                "delivery_profile": delivery_profile,
                "created_at": self._now(),
                "updated_at": self._now(),
                "assigned_at": self._now(),
            }
            tasks.append(task)
            self._write_tasks_json(tasks)
            logger.info("task.created id=%s owner=%s workstream=%s title=%s", task_id, resolved_owner, workstream, title[:60])

        self.bus.write_command(
            task_id,
            {
                "task_id": task_id,
                "owner": resolved_owner,
                "title": title,
                "description": description,
                "task_type": normalized_task_type,
                "workstream": workstream,
                "project_root": normalized_root,
                "project_name": normalized_name,
                "team_id": normalized_team_id or None,
                "parent_task_id": normalized_parent,
                "tags": task_tags,
                "acceptance_criteria": acceptance_criteria,
                "delivery_profile": delivery_profile,
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
                "project_name": normalized_name,
                "team_id": normalized_team_id or None,
                "tags": task_tags,
            },
            source=self.manager_agent(),
        )
        return task

    def orchestrator_create_github_issue(
        self,
        bug_id: str,
        repo: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a GitHub issue from an orchestrator bug record.
        This is an MCP tool that wraps _create_github_issue_from_bug.
        """
        with self._state_lock():
            bugs = self._read_json_list(self.bugs_path)
            bug = next((b for b in bugs if b["id"] == bug_id), None)
            if bug is None:
                raise ValueError(f"Bug not found: {bug_id}")

            return self._create_github_issue_from_bug(bug, repo_full_name=repo)

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
                self._write_tasks_json(tasks)

        return {"deduped_count": len(deduped), "deduped": deduped}

    def list_tasks(
        self,
        status: Optional[str] = None,
        owner: Optional[str] = None,
        project_name: Optional[str] = None,
        project_root: Optional[str] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        lane: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        tasks = self._read_json(self.tasks_path)
        if not isinstance(tasks, list):
            return []

        normalized_tags = self._normalize_task_tags(tags=tags) if tags else []
        normalized_project_name = str(project_name or "").strip()
        normalized_project_root = self._safe_resolve(str(project_root).strip()) if project_root else None
        normalized_team_id = str(team_id or "").strip().lower()

        filtered: List[Dict[str, Any]] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            if status and task.get("status") != status:
                continue
            if owner and task.get("owner") != owner:
                continue
            if normalized_team_id and str(task.get("team_id", "")).strip().lower() != normalized_team_id:
                continue
            if lane == "wingman":
                # Wingman lane: tasks that have a pending or rejected review gate.
                rg = task.get("review_gate")
                if not isinstance(rg, dict) or rg.get("status") not in {"pending", "rejected"}:
                    continue
            elif lane:
                # Other lanes could be added here; for now, ignore unknown lanes.
                pass
            if normalized_project_name and str(task.get("project_name", "")).strip() != normalized_project_name:
                continue
            if normalized_project_root is not None:
                task_root = self._safe_resolve(str(task.get("project_root", "")).strip())
                if task_root is None or task_root != normalized_project_root:
                    continue
            if normalized_tags:
                task_tags = set(self._normalize_task_tags(tags=task.get("tags")))
                if not set(normalized_tags).issubset(task_tags):
                    continue
            filtered.append(task)
        return filtered

    def list_tasks_for_owner(self, owner: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = [task for task in self.list_tasks() if task.get("owner") == owner]
        if status:
            tasks = [task for task in tasks if task.get("status") == status]
        return tasks

    def list_sub_tasks(self, parent_task_id: str) -> List[Dict[str, Any]]:
        """Return all tasks whose parent_task_id matches the given id."""
        tasks = self._read_json(self.tasks_path)
        if not isinstance(tasks, list):
            return []
        return [t for t in tasks if isinstance(t, dict) and t.get("parent_task_id") == parent_task_id]

    def _claim_cooldown_seconds(self) -> float:
        """Return the anti-spam cooldown window (seconds) for empty claim attempts."""
        raw = self.policy.triggers.get("claim_cooldown_seconds", 5)
        try:
            return max(0.0, float(raw))
        except Exception:
            return 5.0

    def claim_next_task(
        self,
        owner: str,
        instance_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        self._assert_agent_operational(owner)
        normalized_team_id = str(team_id or "").strip().lower()

        # --- Anti-spam cooldown for rapid empty claims ---
        # Uses tasks file mtime to detect new work; only throttles when the
        # tasks file is unchanged since the last empty claim.
        cooldown = self._claim_cooldown_seconds()
        if cooldown > 0:
            last_info = self._claim_cooldowns.get(owner)
            if last_info is not None:
                last_ts, last_mtime = last_info
                elapsed = time.monotonic() - last_ts
                if elapsed < cooldown:
                    try:
                        current_mtime = self.tasks_path.stat().st_mtime
                    except OSError:
                        current_mtime = 0.0
                    if current_mtime == last_mtime:
                        remaining = cooldown - elapsed
                        return {
                            "throttled": True,
                            "backoff_seconds": round(remaining, 2),
                            "cooldown_seconds": cooldown,
                            "message": "claim_cooldown: too many rapid empty claims",
                        }

        # Treat a claim attempt as proof-of-life from the team_member.
        with self._state_lock():
            self._refresh_agent_presence_unlocked(owner)
            explicit_instance_id = str(instance_id or "").strip()
            lease_owner_instance = explicit_instance_id or self._current_agent_instance_id_unlocked(owner)
            owner_scope = self._agent_project_scope_unlocked(owner)
            tasks = self._read_json(self.tasks_path)
            overrides = self._read_json(self.claim_overrides_path)
            if not isinstance(overrides, dict):
                overrides = {}
            override_entry = overrides.get(owner)
            override_task_id = ""
            override_correlation_id: Optional[str] = None
            if isinstance(override_entry, str) and override_entry.strip():
                override_task_id = override_entry.strip()
            elif isinstance(override_entry, dict):
                task_id_raw = override_entry.get("task_id")
                if isinstance(task_id_raw, str) and task_id_raw.strip():
                    override_task_id = task_id_raw.strip()
                corr_raw = override_entry.get("correlation_id")
                if isinstance(corr_raw, str) and corr_raw.strip():
                    override_correlation_id = corr_raw.strip()
            if override_task_id:
                forced = next((t for t in tasks if t.get("id") == override_task_id and t.get("owner") == owner), None)
                if forced and forced.get("status") in {"assigned", "bug_open"}:
                    if normalized_team_id and str(forced.get("team_id", "")).strip().lower() != normalized_team_id:
                        forced = None
                if forced and forced.get("status") in {"assigned", "bug_open"}:
                    self._assert_task_project_scope(
                        forced,
                        operation="claim_override",
                        project_root=owner_scope.get("project_root"),
                        project_name=str(owner_scope.get("project_name", "")),
                    )
                    forced["status"] = "in_progress"
                    forced["updated_at"] = self._now()
                    forced["claimed_at"] = forced["updated_at"]
                    self._issue_task_lease_unlocked(task=forced, owner=owner, owner_instance_id=lease_owner_instance)
                    self._write_tasks_json(tasks)
                    del overrides[owner]
                    self._write_json(self.claim_overrides_path, overrides)
                    self.bus.emit(
                        "task.claimed",
                        {
                            "task_id": forced["id"],
                            "owner": owner,
                            "via": "manager_override",
                            "correlation_id": override_correlation_id,
                        },
                        source=owner,
                    )
                    if override_correlation_id:
                        self.bus.emit(
                            "dispatch.ack",
                            {
                                "correlation_id": override_correlation_id,
                                "agent": owner,
                                "instance_id": lease_owner_instance,
                                "task_id": forced["id"],
                                "ack_type": "claim_override_consumed",
                            },
                            source=owner,
                        )
                    # Successful claim: clear any cooldown for this agent.
                    self._claim_cooldowns.pop(owner, None)
                    return forced
                # Override no longer valid; clear it and continue normal claim order.
                del overrides[owner]
                self._write_json(self.claim_overrides_path, overrides)

            for task in tasks:
                if task.get("owner") != owner:
                    continue
                if task.get("status") not in {"assigned", "bug_open"}:
                    continue
                if normalized_team_id and str(task.get("team_id", "")).strip().lower() != normalized_team_id:
                    continue
                if not self._task_matches_project_scope(
                    task,
                    project_root=owner_scope.get("project_root"),
                    project_name=str(owner_scope.get("project_name", "")),
                ):
                    # Legacy mixed-project residue must not be claimed in this project runtime.
                    continue

                task["status"] = "in_progress"
                task["updated_at"] = self._now()
                task["claimed_at"] = task["updated_at"]
                self._issue_task_lease_unlocked(task=task, owner=owner, owner_instance_id=lease_owner_instance)
                self._write_tasks_json(tasks)
                logger.info("task.claimed id=%s owner=%s title=%s", task["id"], owner, str(task.get("title", ""))[:60])
                self.bus.emit(
                    "task.claimed",
                    {"task_id": task["id"], "owner": owner},
                    source=owner,
                )
                # Successful claim: clear any cooldown for this agent.
                self._claim_cooldowns.pop(owner, None)
                return task

        # Empty claim: start cooldown window with current tasks file mtime.
        if cooldown > 0:
            try:
                mtime = self.tasks_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            self._claim_cooldowns[owner] = (time.monotonic(), mtime)
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
            correlation_id = f"CMD-{uuid.uuid4().hex[:10]}"
            overrides[agent] = {
                "task_id": task_id,
                "correlation_id": correlation_id,
                "source": source,
                "created_at": self._now(),
            }
            self._write_json(self.claim_overrides_path, overrides)
        self.bus.emit(
            "manager.claim_override",
            {"agent": agent, "task_id": task_id, "correlation_id": correlation_id},
            source=source,
        )
        self.bus.emit(
            "dispatch.command",
            {
                "correlation_id": correlation_id,
                "command_type": "claim_override",
                "agent": agent,
                "task_id": task_id,
            },
            source=source,
        )
        return {"ok": True, "agent": agent, "task_id": task_id, "correlation_id": correlation_id}

    def emit_stale_claim_override_noops(
        self,
        source: str,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            raise ValueError(f"leader_mismatch: source={source}, current_leader={manager}")
        threshold = max(5, int(timeout_seconds))
        emitted: List[Dict[str, Any]] = []
        now_dt = datetime.now(timezone.utc)
        with self._state_lock():
            overrides = self._read_json(self.claim_overrides_path)
            if not isinstance(overrides, dict):
                return {"emitted_count": 0, "emitted": [], "timeout_seconds": threshold}
            changed = False
            tasks = self._read_json(self.tasks_path)
            for agent, entry in list(overrides.items()):
                if not isinstance(entry, dict):
                    continue
                corr = entry.get("correlation_id")
                task_id = entry.get("task_id")
                created_at_raw = entry.get("created_at")
                if not isinstance(corr, str) or not corr.strip():
                    continue
                if not isinstance(task_id, str) or not task_id.strip():
                    continue
                if entry.get("noop_emitted_at"):
                    continue
                try:
                    created_dt = datetime.fromisoformat(str(created_at_raw))
                except Exception as _e:
                    logger.debug("claim_noop: failed to parse created_at=%s: %s", created_at_raw, _e)
                    created_dt = now_dt
                age = int((now_dt - created_dt).total_seconds())
                if age < threshold:
                    continue
                # Suppress noop if override was already consumed or task advanced.
                task = next((t for t in tasks if t.get("id") == task_id), None)
                if task and task.get("status") not in {"assigned", "bug_open"}:
                    entry["noop_suppressed_at"] = self._now()
                    entry["noop_suppressed_reason"] = f"task_status={task.get('status')}"
                    changed = True
                    continue
                entry["noop_emitted_at"] = self._now()
                entry["noop_reason"] = "claim_override_timeout"
                changed = True
                emitted.append(
                    {
                        "agent": agent,
                        "task_id": task_id,
                        "correlation_id": corr,
                        "age_seconds": age,
                        "reason": "claim_override_timeout",
                    }
                )
            if changed:
                self._write_json(self.claim_overrides_path, overrides)
        for item in emitted:
            self.bus.emit(
                "dispatch.noop",
                {
                    "correlation_id": item["correlation_id"],
                    "command_type": "claim_override",
                    "agent": item["agent"],
                    "task_id": item["task_id"],
                    "reason": item["reason"],
                    "age_seconds": item["age_seconds"],
                },
                source=source,
            )
        return {"emitted_count": len(emitted), "emitted": emitted, "timeout_seconds": threshold}

    def set_task_status(self, task_id: str, status: str, source: str, note: str = "") -> Dict[str, Any]:
        manager = self.manager_agent()
        if source != manager:
            self._assert_agent_operational(source)
        normalized = str(status).strip().lower()
        # Completion must flow through ingest_report/submit_report so manager validation
        # can enforce commit + test evidence and emit consistent report events.
        if normalized in {"done", "reported"} and source != self.manager_agent():
            raise ValueError("Use orchestrator_submit_report for completion/report transitions")
        # superseded/archived are manager-only lifecycle transitions.
        if normalized in {"superseded", "archived"} and source != self.manager_agent():
            raise ValueError("superseded/archived transitions require manager authority")
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
            if source == owner:
                source_scope = self._agent_project_scope_unlocked(source)
                self._assert_task_project_scope(
                    task=task,
                    operation="set_task_status",
                    project_root=source_scope.get("project_root"),
                    project_name=str(source_scope.get("project_name", "")),
                )

            task["status"] = status
            task["updated_at"] = self._now()
            if normalized == "blocked":
                task["blocked_at"] = task["updated_at"]
            elif normalized == "in_progress":
                task["claimed_at"] = task["updated_at"]
            elif normalized in {"superseded", "archived"}:
                task[f"{normalized}_at"] = task["updated_at"]
            self._write_tasks_json(tasks)
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
            agent_scope = self._agent_project_scope_unlocked(str(report["agent"]))
            self._assert_task_project_scope(
                task=task,
                operation="ingest_report",
                project_root=agent_scope.get("project_root"),
                project_name=str(agent_scope.get("project_name", "")),
            )
            if task.get("owner") != report["agent"]:
                raise ValueError(
                    f"Report agent '{report['agent']}' does not match task owner '{task.get('owner')}'"
                )
            report["project_root"] = str(task.get("project_root", ""))
            report["project_name"] = str(task.get("project_name", ""))
            report["tags"] = self._normalize_task_tags(tags=task.get("tags"))

            # --- Report Deduplication ---
            existing_report = self.bus.read_report(task_id=task_id)
            if existing_report and existing_report.get("commit_sha") == report.get("commit_sha"):
                self.bus.emit(
                    "task.reported.deduplicated",
                    {
                        "task_id": task_id,
                        "agent": report["agent"],
                        "commit_sha": report["commit_sha"],
                        "status": report["status"],
                        "reason": "report with same commit_sha already exists",
                    },
                    source=report["agent"],
                )
                return {**existing_report, "deduplicated": True}
            # --- End Report Deduplication ---

            # Pass the current mocked time as mtime for consistent testing of cleanup logic
            report_mtime = datetime.fromisoformat(self._now()).timestamp()
            self.bus.write_report(task_id=task_id, report=report, mtime=report_mtime)

            review_gate = report.get("review_gate")
            if isinstance(review_gate, dict):
                task["review_gate"] = self._normalize_review_gate(review_gate)
                task["review_gate_updated_at"] = self._now()

            self_review = report.get("self_review")
            if isinstance(self_review, dict):
                # Process self-review findings and potentially create bug records
                if isinstance(self_review.get("rounds"), list):
                    for idx, s_round in enumerate(self_review["rounds"]):
                        if isinstance(s_round, dict) and s_round.get("verdict") == "needs_revision":
                            # If worker did not already create a bug, create one now.
                            if not s_round.get("bug_id"):
                                repro_steps = (
                                    f"Self-review findings for task {task_id} "
                                    f"(Round {s_round.get('round_number', idx + 1)}):\n"
                                    + "\n".join(s_round.get("findings", []))
                                )
                                bug = self._open_bug(
                                    source_task=task_id,
                                    owner=report["agent"],
                                    severity="medium",
                                    repro_steps=repro_steps,
                                    expected="All self-review issues to be resolved.",
                                    actual=f"Self-review round {s_round.get('round_number', idx + 1)} "
                                    "revealed outstanding issues.",
                                )
                                s_round["bug_id"] = bug.get("id")
                task["self_review"] = self_review
                task["self_review_updated_at"] = self._now()

            task["status"] = "reported"
            task["updated_at"] = self._now()
            task["reported_at"] = task["updated_at"]
            task["lease"] = None
            self._write_tasks_json(tasks)

        self.bus.emit(
            "task.reported",
            {"task_id": task_id, "agent": report["agent"], "status": report["status"]},
            source=report["agent"],
        )
        return report

    def renew_task_lease(self, task_id: str, agent: str, lease_id: str, instance_id: Optional[str] = None) -> Dict[str, Any]:
        self._assert_agent_operational(agent)
        lease_id_norm = str(lease_id).strip()
        if not lease_id_norm:
            raise ValueError("lease_id must be a non-empty string")
        with self._state_lock():
            self._refresh_agent_presence_unlocked(agent)
            tasks = self._read_json(self.tasks_path)
            task = next((item for item in tasks if item.get("id") == task_id), None)
            if task is None:
                raise ValueError(f"Task not found: {task_id}")
            agent_scope = self._agent_project_scope_unlocked(agent)
            self._assert_task_project_scope(
                task=task,
                operation="renew_task_lease",
                project_root=agent_scope.get("project_root"),
                project_name=str(agent_scope.get("project_name", "")),
            )
            if str(task.get("owner", "")) != agent:
                raise ValueError(f"lease_owner_mismatch: task_owner={task.get('owner')} agent={agent}")
            lease = task.get("lease")
            if not isinstance(lease, dict):
                raise ValueError("lease_missing")
            if str(lease.get("lease_id", "")).strip() != lease_id_norm:
                raise ValueError("lease_id_mismatch")
            owner_instance_id = str(lease.get("owner_instance_id", "")).strip()
            explicit_instance_id = str(instance_id or "").strip()
            current_instance_id = explicit_instance_id or self._current_agent_instance_id_unlocked(agent)
            if owner_instance_id and current_instance_id and owner_instance_id != current_instance_id:
                raise ValueError(
                    f"lease_instance_mismatch: lease_owner_instance={owner_instance_id} current_instance={current_instance_id}"
                )
            if self._lease_expired(lease):
                raise ValueError("lease_expired")
            now = self._now()
            lease["renewed_at"] = now
            ttl = self._lease_ttl_seconds()
            lease["ttl_seconds"] = ttl
            lease["expires_at"] = self._timestamp_plus_seconds(ttl)
            task["lease"] = lease
            task["updated_at"] = now
            self._write_tasks_json(tasks)
        self.bus.emit(
            "task.lease_renewed",
            {"task_id": task_id, "agent": agent, "lease_id": lease_id_norm, "instance_id": str(instance_id or "").strip() or None},
            source=agent,
        )
        return {
            "task_id": task_id,
            "agent": agent,
            "instance_id": str(instance_id or "").strip() or None,
            "lease": dict(lease),
        }

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
        # Periodic maintenance: compact event bus and cleanup old reports.
        self.compact_events()
        report_retention_days = self.policy.triggers.get("report_retention_days", 30)
        self._cleanup_old_reports(max_age_seconds=report_retention_days * 24 * 60 * 60)

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
                self._write_tasks_json(tasks)
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
                self._write_tasks_json(tasks)

            return {
                "reassigned_count": len(reassigned),
                "threshold_seconds": threshold,
                "reassigned": reassigned,
                "active_agents": active_names,
                "timestamp": now.isoformat(),
            }

    def recover_expired_task_leases(
        self,
        source: str,
        stale_after_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        threshold = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
        with self._state_lock():
            tasks = self._read_json(self.tasks_path)
            blockers = self._read_json_list(self.blockers_path)
            active_agents = self.list_agents(active_only=True, stale_after_seconds=threshold)
            active_names = [a.get("agent") for a in active_agents if isinstance(a.get("agent"), str)]
            recoveries: List[Dict[str, Any]] = []
            changed_tasks = False
            changed_blockers = False

            for task in tasks:
                if task.get("status") != "in_progress":
                    continue
                lease = task.get("lease")
                if not isinstance(lease, dict):
                    continue
                if not self._lease_expired(lease):
                    continue

                task_id = str(task.get("id", ""))
                owner = str(task.get("owner", ""))
                lease_owner_instance = str(lease.get("owner_instance_id", ""))
                record: Dict[str, Any] = {
                    "task_id": task_id,
                    "owner": owner,
                    "lease_id": str(lease.get("lease_id", "")),
                    "lease_owner_instance_id": lease_owner_instance,
                    "reason": "lease_expired",
                }

                eligible_owner = owner if owner in active_names else None
                new_owner = eligible_owner or self._pick_reassignment_owner(
                    task=task,
                    active_names=active_names,
                    tasks=tasks,
                )

                task["lease"] = None
                task["lease_recovery_at"] = self._now()
                changed_tasks = True

                if new_owner:
                    previous_owner = owner
                    task["owner"] = new_owner
                    task["status"] = "assigned"
                    task["updated_at"] = self._now()
                    if new_owner != previous_owner:
                        task["reassigned_from"] = previous_owner
                        task["reassigned_reason"] = "lease_expired_recovery"
                        event_type = "task.reassigned_lease_expired"
                        record["to_owner"] = new_owner
                    else:
                        event_type = "task.requeued_lease_expired"
                    recoveries.append({**record, "action": "requeued", "to_owner": new_owner})
                    self.bus.emit(event_type, {**record, "to_owner": new_owner}, source=source)
                    continue

                task["status"] = "blocked"
                task["updated_at"] = self._now()
                task["lease_recovery_reason"] = "no_eligible_worker"
                blocker = {
                    "id": f"BLK-{uuid.uuid4().hex[:8]}",
                    "task_id": task_id,
                    "agent": owner,
                    "question": (
                        "Lease expired for in-progress task and no eligible same-project active worker "
                        "was available for recovery. How should this task proceed?"
                    ),
                    "options": [],
                    "severity": "high",
                    "status": "open",
                    "created_at": self._now(),
                }
                blockers.append(blocker)
                changed_blockers = True
                recoveries.append({**record, "action": "blocked", "blocker_id": blocker["id"]})
                self.bus.emit(
                    "task.lease_expired_blocked",
                    {**record, "blocker_id": blocker["id"]},
                    source=source,
                )

                # Create a bug record for the runtime defect
                bug = self._open_bug(
                    source_task=task_id,
                    owner=owner,
                    severity="high",
                    repro_steps=(
                        f"Task {task_id} lease expired and no eligible worker was available for recovery. "
                        f"A blocker (ID: {blocker['id']}) was created."
                    ),
                    expected="Task lease to be renewed or task to be reassigned to an active worker.",
                    actual="Task lease expired, leading to a blocked task and no automatic recovery.",
                )
                task["runtime_defect_bug_id"] = bug["id"] # Add bug ID to task for traceability


            if changed_tasks:
                self._write_tasks_json(tasks)
            if changed_blockers:
                self._write_json(self.blockers_path, blockers)

            return {
                "recovered_count": len(recoveries),
                "recovered": recoveries,
                "active_agents": active_names,
                "threshold_seconds": threshold,
            }

    def run_quality_gates(self, task: Dict[str, Any], report: Dict[str, Any]) -> QualityGateOutcome:
        """Run policy-configured quality gates against a task report."""
        gates_config = self.policy.triggers.get("quality_gates", {})
        return run_quality_gates(report=report, task=task, gates_config=gates_config)

    def self_review_config(self) -> SelfReviewConfig:
        """Return the policy-configured self-review loop settings."""
        return SelfReviewConfig.from_policy(self.policy.triggers)

    def _cleanup_old_reports(self, max_age_seconds: int = 30 * 24 * 60 * 60) -> int:
        """Removes old reports from the bus/reports directory."""
        removed_count = 0
        now = datetime.fromisoformat(self._now()).timestamp()
        # No need for a separate _state_lock here as it's typically called within a locked context
        # or the bus.write_report/read_report handles file locks for individual reports.
        # This operation is more about directory management than shared state.
        for report_file in self.bus.reports_dir.iterdir():
            if report_file.is_file() and report_file.suffix == ".json":
                try:
                    modified_time = report_file.stat().st_mtime
                    if (now - modified_time) > max_age_seconds:
                        report_file.unlink()
                        removed_count += 1 # Removed_count was incremented twice.
                        self.bus.emit(
                            "report.cleaned",
                            {"file": str(report_file.name), "reason": "exceeded max age"},
                            source="orchestrator",
                        )
                except OSError as e:
                    print(f"WARNING: Could not remove old report file {report_file}: {e}", file=sys.stderr, flush=True)
        return removed_count

    def validate_task(
        self,
        task_id: str,
        passed: bool,
        notes: str,
        source: str,
        quality_gate_outcome: Optional[QualityGateOutcome] = None,
    ) -> Dict[str, Any]:
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
                task["validated_at"] = self._now()
                self._close_bugs_for_task(task_id=task_id, note=notes)
                event = "validation.passed"
                payload = {"task_id": task_id, "owner": task["owner"], "notes": notes}
            else:
                task["status"] = "bug_open"
                task["validated_at"] = self._now()
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

            review_gate_snapshot = None
            if isinstance(task.get("review_gate"), dict):
                review_gate_snapshot = dict(task["review_gate"])

            quality_gate_snapshot = None
            if quality_gate_outcome is not None:
                quality_gate_snapshot = {
                    "all_passed": quality_gate_outcome.all_passed,
                    "summary": quality_gate_outcome.summary(),
                    "results": [
                        {"gate": r.gate, "passed": r.passed, "policy": r.policy, "message": r.message}
                        for r in quality_gate_outcome.results
                    ],
                }

            task["validation_gate"] = {
                "validator_agent": source,
                "validator_role": "leader",
                "decision": "accepted" if passed else "rejected",
                "decision_reason": notes,
                "decided_at": self._now(),
                "review_gate": review_gate_snapshot,
                "quality_gate": quality_gate_snapshot,
            }
            if review_gate_snapshot is not None:
                payload["review_gate"] = review_gate_snapshot
            if quality_gate_snapshot is not None:
                payload["quality_gate"] = quality_gate_snapshot

            task["updated_at"] = self._now()
            self._write_tasks_json(tasks)
        decision = "ACCEPTED" if passed else "REJECTED"
        logger.info("task.validated id=%s decision=%s owner=%s notes=%s", task_id, decision, task.get("owner"), notes[:80])
        self.bus.emit(event, payload, source=source)
        return payload

    def list_bugs(self, status: Optional[str] = None, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        bugs = self._read_json_list(self.bugs_path)
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
            agent_scope = self._agent_project_scope_unlocked(agent)
            self._assert_task_project_scope(
                task=task,
                operation="raise_blocker",
                project_root=agent_scope.get("project_root"),
                project_name=str(agent_scope.get("project_name", "")),
            )

            task["status"] = "blocked"
            task["updated_at"] = self._now()
            self._write_tasks_json(tasks)

        blocker_id = f"BLK-{uuid.uuid4().hex[:8]}"
        blocker = {
            "id": blocker_id,
            "task_id": task_id,
            "agent": agent,
            "project_root": task.get("project_root"),
            "project_name": task.get("project_name"),
            "tags": self._normalize_task_tags(tags=task.get("tags")),
            "question": question,
            "options": options or [],
            "severity": severity,
            "status": "open",
            "created_at": self._now(),
        }

        with self._state_lock():
            blockers = self._read_json_list(self.blockers_path)
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
        blockers = self._read_json_list(self.blockers_path)
        if status:
            blockers = [blk for blk in blockers if blk.get("status") == status]
        if agent:
            blockers = [blk for blk in blockers if blk.get("agent") == agent]
        return blockers

    def resolve_blocker(self, blocker_id: str, resolution: str, source: str) -> Dict[str, Any]:
        with self._state_lock():
            blockers = self._read_json_list(self.blockers_path)
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
                self._write_tasks_json(tasks)

        self.bus.emit(
            "blocker.resolved",
            {"blocker_id": blocker_id, "task_id": blocker.get("task_id"), "resolution": resolution},
            source=source,
        )
        return blocker

    # ------------------------------------------------------------------
    # Auto-resolution of stale / meta blockers
    # ------------------------------------------------------------------

    def _is_meta_blocker(self, blocker: Dict[str, Any]) -> bool:
        """Return True if the blocker is a meta/watchdog blocker rather
        than a genuine user-input-required decision."""
        question = str(blocker.get("question", "")).lower()
        for pattern in _META_BLOCKER_PATTERNS:
            if pattern.lower() in question:
                return True
        return False

    def auto_resolve_stale_blockers(
        self,
        source: str = "auto_policy",
        stale_after_seconds: int = 3600,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Auto-resolve open meta/watchdog blockers past their stale age.

        Only meta blockers (watchdog, project-mismatch, stale-task) are
        eligible.  Blockers that require genuine user input are never
        auto-resolved.

        Returns a summary dict with resolved IDs and skipped counts.
        """
        open_blockers = self.list_blockers(status="open")
        now = datetime.now(timezone.utc)
        resolved: List[Dict[str, Any]] = []
        skipped_actionable = 0
        skipped_young = 0

        for blocker in open_blockers:
            if len(resolved) >= limit:
                break

            # Never auto-resolve actionable (user-input) blockers.
            if not self._is_meta_blocker(blocker):
                skipped_actionable += 1
                continue

            # Check age.
            created_at = blocker.get("created_at", "")
            try:
                created = datetime.fromisoformat(created_at)
                age_seconds = (now - created).total_seconds()
            except (ValueError, TypeError):
                age_seconds = float("inf")  # Unknown age → treat as stale.

            if age_seconds < stale_after_seconds:
                skipped_young += 1
                continue

            reason_code = "stale_meta_blocker"
            if "project" in str(blocker.get("question", "")).lower():
                reason_code = "project_mismatch_blocker"
            elif "watchdog" in str(blocker.get("question", "")).lower():
                reason_code = "stale_watchdog_blocker"

            resolution = (
                f"Auto-resolved by {source}: {reason_code} "
                f"(age {int(age_seconds)}s > threshold {stale_after_seconds}s)"
            )

            self.resolve_blocker(
                blocker_id=blocker["id"],
                resolution=resolution,
                source=source,
            )

            self.bus.emit(
                "blocker.auto_resolved",
                {
                    "blocker_id": blocker["id"],
                    "task_id": blocker.get("task_id"),
                    "reason_code": reason_code,
                    "age_seconds": int(age_seconds),
                    "threshold_seconds": stale_after_seconds,
                },
                source=source,
            )

            resolved.append({
                "blocker_id": blocker["id"],
                "task_id": blocker.get("task_id"),
                "reason_code": reason_code,
                "age_seconds": int(age_seconds),
            })

        return {
            "resolved": resolved,
            "resolved_count": len(resolved),
            "skipped_actionable": skipped_actionable,
            "skipped_young": skipped_young,
            "threshold_seconds": stale_after_seconds,
        }

    # ------------------------------------------------------------------
    # Consult-only team review (no task/execution side effects)
    # ------------------------------------------------------------------

    def create_consult(
        self,
        source: str,
        consult_type: str,
        question: str,
        context: str = "",
        target_agents: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a consult-only review request.

        This does NOT create a task, claim, or trigger any execution.
        It stores a lightweight consult record and emits an event so
        targeted agents can respond asynchronously.
        """
        valid_types = ("design", "bug", "architecture", "general")
        if consult_type not in valid_types:
            raise ValueError(f"Invalid consult_type '{consult_type}'. Must be one of: {', '.join(valid_types)}")

        consult_id = f"CONSULT-{uuid.uuid4().hex[:8]}"
        consult = {
            "id": consult_id,
            "source": source,
            "consult_type": consult_type,
            "question": question,
            "context": context,
            "target_agents": target_agents or [],
            "responses": [],
            "status": "open",
            "created_at": self._now(),
        }

        with self._state_lock():
            consults = self._read_json_list(self.consults_path)
            consults.append(consult)
            self._write_json(self.consults_path, consults)

        payload: Dict[str, Any] = {
            "consult_id": consult_id,
            "source": source,
            "consult_type": consult_type,
            "question": question,
        }
        if target_agents:
            payload["audience"] = target_agents
        self.bus.emit("consult.created", payload, source=source)
        return consult

    def respond_consult(
        self,
        consult_id: str,
        agent: str,
        body: str,
    ) -> Dict[str, Any]:
        """Add a structured response to a consult request.

        Does not create tasks or trigger execution. The consult is
        closed automatically when all targeted agents have responded,
        or it can remain open for additional input.
        """
        with self._state_lock():
            consults = self._read_json_list(self.consults_path)
            consult = next((c for c in consults if c["id"] == consult_id), None)
            if consult is None:
                raise ValueError(f"Consult not found: {consult_id}")
            if consult.get("status") == "closed":
                raise ValueError(f"Consult already closed: {consult_id}")

            response = {
                "agent": agent,
                "body": body,
                "responded_at": self._now(),
            }
            consult["responses"].append(response)
            consult["updated_at"] = self._now()

            # Auto-close when all targeted agents have responded.
            target_agents = consult.get("target_agents", [])
            if target_agents:
                responded_agents = {r["agent"] for r in consult["responses"]}
                if set(target_agents).issubset(responded_agents):
                    consult["status"] = "closed"
                    consult["closed_at"] = self._now()

            self._write_json(self.consults_path, consults)

        self.bus.emit(
            "consult.responded",
            {
                "consult_id": consult_id,
                "agent": agent,
                "status": consult["status"],
            },
            source=agent,
        )
        return consult

    def list_consults(
        self,
        status: Optional[str] = None,
        consult_type: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List consults with optional filtering.

        ``agent`` matches either source or target_agents.
        """
        consults = self._read_json_list(self.consults_path)
        if status:
            consults = [c for c in consults if c.get("status") == status]
        if consult_type:
            consults = [c for c in consults if c.get("consult_type") == consult_type]
        if agent:
            consults = [
                c for c in consults
                if c.get("source") == agent or agent in c.get("target_agents", [])
            ]
        return consults

    # ------------------------------------------------------------------
    # Stacked PR chains
    # ------------------------------------------------------------------

    def create_pr_stack(
        self,
        repo: str,
        title: str,
        *,
        task_ids: Optional[List[str]] = None,
        base_branch: str = "main",
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new PR stack and persist it."""
        stack = _pr_stack.create_stack(
            repo=repo,
            title=title,
            task_ids=task_ids,
            base_branch=base_branch,
            created_by=created_by,
        )
        with self._state_lock():
            stacks = self._read_json_list(self.pr_stacks_path)
            stacks.append(stack)
            self._write_json(self.pr_stacks_path, stacks)
        self.bus.emit(
            "prstack.created",
            {"stack_id": stack["id"], "repo": repo, "title": title},
            source=created_by or "orchestrator",
        )
        return stack

    def add_pr_to_stack(
        self,
        stack_id: str,
        *,
        branch: str,
        title: str,
        task_id: Optional[str] = None,
        pr_number: Optional[int] = None,
        position: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Add a PR entry to an existing stack. Returns the new PR entry."""
        with self._state_lock():
            stacks = self._read_json_list(self.pr_stacks_path)
            stack = next((s for s in stacks if s["id"] == stack_id), None)
            if stack is None:
                raise ValueError(f"PR stack not found: {stack_id}")
            pr_entry = _pr_stack.add_pr_to_stack(
                stack,
                branch=branch,
                title=title,
                task_id=task_id,
                pr_number=pr_number,
                position=position,
            )
            self._write_json(self.pr_stacks_path, stacks)
        self.bus.emit(
            "prstack.pr_added",
            {"stack_id": stack_id, "pr_id": pr_entry["id"], "branch": branch},
            source="orchestrator",
        )
        return pr_entry

    def process_pr_stack_merge(
        self,
        stack_id: str,
        pr_id: str,
    ) -> Dict[str, Any]:
        """Handle a merge event for a stacked PR.

        Returns a summary including any newly-ungated child PRs.
        """
        with self._state_lock():
            stacks = self._read_json_list(self.pr_stacks_path)
            stack = next((s for s in stacks if s["id"] == stack_id), None)
            if stack is None:
                raise ValueError(f"PR stack not found: {stack_id}")
            ungated = _pr_stack.process_merge_event(stack, pr_id)
            self._write_json(self.pr_stacks_path, stacks)

        for child in ungated:
            self.bus.emit(
                "prstack.pr_ungated",
                {
                    "stack_id": stack_id,
                    "pr_id": child["id"],
                    "branch": child["branch"],
                    "base_branch": child["base_branch"],
                },
                source="orchestrator",
            )
        if stack["state"] == "merged":
            self.bus.emit(
                "prstack.merged",
                {"stack_id": stack_id, "repo": stack["repo"]},
                source="orchestrator",
            )
        return {
            "stack_id": stack_id,
            "stack_state": stack["state"],
            "merged_pr_id": pr_id,
            "ungated_prs": [{"id": c["id"], "branch": c["branch"]} for c in ungated],
        }

    def get_pr_stacks(
        self,
        *,
        repo: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List PR stacks, optionally filtered by repo or state."""
        stacks = self._read_json_list(self.pr_stacks_path)
        if repo:
            stacks = [s for s in stacks if s.get("repo") == repo]
        if state:
            stacks = [s for s in stacks if s.get("state") == state]
        return stacks

    def get_stack_status(self, stack_id: str) -> Dict[str, Any]:
        """Return readiness summary for a PR stack."""
        stacks = self._read_json_list(self.pr_stacks_path)
        stack = next((s for s in stacks if s["id"] == stack_id), None)
        if stack is None:
            raise ValueError(f"PR stack not found: {stack_id}")
        ready_prs = _pr_stack.get_next_ready_prs(stack)
        return {
            "stack_id": stack_id,
            "state": stack["state"],
            "total_prs": len(stack["prs"]),
            "merged_count": sum(1 for p in stack["prs"] if p["state"] == "merged"),
            "gated_count": sum(1 for p in stack["prs"] if p.get("gated")),
            "next_ready": [{"id": p["id"], "branch": p["branch"]} for p in ready_prs],
        }

        return {
            "status": "success",
            "action": "simulated_github_issue_creation",
            "task_id": task_id,
            "issue_title": issue_title,
            "log_message": log_message,
        }

    def process_github_handoff_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a github.handoff_required event and simulate GitHub API interaction.

        This method acts as a placeholder for actual GitHub API calls (e.g., creating issues,
        commenting on PRs). It logs the intended actions and returns a summary.
        """
        task_id = payload.get("task_id")
        ci_state = payload.get("ci_state")
        orchestrator_status = payload.get("orchestrator_status")
        conclusion = payload.get("conclusion")
        normalized_ci = payload.get("normalized_ci", {})
        action_required = payload.get("action_required")

        log_message = (
            f"GITHUB HANDOFF REQUIRED for task {task_id}: "
            f"CI State='{ci_state}', Orchestrator Status='{orchestrator_status}', "
            f"Conclusion='{conclusion}'. Action: '{action_required}'"
        )
        print(f"DEBUG: {log_message}", file=sys.stderr, flush=True)

        # Placeholder for actual GitHub API interaction
        # In a real implementation, you would use a library like PyGithub here.
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            print("WARNING: GITHUB_TOKEN environment variable not set. Cannot perform GitHub API actions.", file=sys.stderr, flush=True)
            return {
                "status": "skipped",
                "reason": "GITHUB_TOKEN missing",
                "task_id": task_id,
                "log_message": log_message,
            }

        # Simulate creating an issue or commenting on a PR
        if action_required == "create_github_issue_or_comment_pr":
            # For simplicity, let's assume we create an issue for failed CI.
            # In a real scenario, you'd check if it's a PR, etc.
            issue_title = f"CI Failed for Task {task_id}: {conclusion}"
            issue_body = (
                f"Automated CI run failed for task **{task_id}**.\n\n"
                f"CI State: `{ci_state}`\n"
                f"GitHub Status: `{normalized_ci.get('status')}`\n"
                f"Conclusion: `{conclusion}`\n"
                f"CI Run URL: {normalized_ci.get('url', 'N/A')}\n\n"
                "Please investigate the failure and address the underlying issues."
            )
            
            # Simulate GitHub API call
            print(f"INFO: Simulating GitHub API call to create issue/comment for task {task_id}", file=sys.stderr, flush=True)
            print(f"  Issue Title: {issue_title}", file=sys.stderr, flush=True)
            print(f"  Issue Body: {issue_body}", file=sys.stderr, flush=True)
            
            # In a real scenario:
            # from github import Github
            # g = Github(github_token)
            # repo = g.get_user().get_repo("your-repo-name") # Need to determine repo context
            # repo.create_issue(title=issue_title, body=issue_body, labels=["bug", "ci-failure"])
            
            return {
                "status": "success",
                "action": "simulated_github_issue_creation",
                "task_id": task_id,
                "issue_title": issue_title,
                "log_message": log_message,
            }
        
        return {
            "status": "unhandled_action",
            "reason": f"No specific handler for action_required: {action_required}",
            "task_id": task_id,
            "log_message": log_message,
        }

    def _find_pr_in_stacks_unlocked(
        self,
        *,
        repo: str,
        pr_number: Optional[int] = None,
        branch: Optional[str] = None,
        head_sha: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Helper to find a PR entry in any stack by number, branch, or SHA.

        Must be called with _state_lock held.
        """
        stacks = self._read_json_list(self.pr_stacks_path)
        for stack in stacks:
            if stack.get("repo") != repo:
                continue
            for pr_entry in stack.get("prs", []):
                matched = False
                if pr_number is not None and pr_entry.get("pr_number") == pr_number:
                    matched = True
                elif branch and pr_entry.get("branch") == branch:
                    if head_sha and pr_entry.get("head_sha") != head_sha and pr_entry.get("head_sha") is not None:
                        matched = False
                    else:
                        matched = True
                elif head_sha and pr_entry.get("head_sha") == head_sha:
                    if not pr_entry.get("pr_number") and not pr_entry.get("branch"):
                        matched = True

                if matched:
                    pr_entry["stack"] = stack
                    return pr_entry
        return None

    def process_github_webhook(self, payload: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Process a GitHub webhook payload, normalize CI results, and update orchestrator tasks."""
        # Extract headers from the payload itself, as the tool definition doesn't pass them separately.
        # This is a convention for our internal MCP tools.
        headers = payload.get("headers", {})
        event_type = headers.get("X-GitHub-Event")
        if not event_type:
            print("WARNING: X-GitHub-Event header missing. Cannot process webhook.", file=sys.stderr, flush=True)
            return {"status": "error", "reason": "X-GitHub-Event header missing"}

        repo_full_name = payload.get("repository", {}).get("full_name")
        if not repo_full_name:
            # Try to get it from the top-level payload if not in a nested 'repository' key
            repo_full_name = payload.get("repo", {}).get("full_name") or payload.get("repository", {}).get("full_name")

            if not repo_full_name:
                print("WARNING: Repository full name missing from payload. Cannot process webhook.", file=sys.stderr, flush=True)
                return {"status": "error", "reason": "repository.full_name missing"}


        processed_summary: Dict[str, Any] = {
            "event_type": event_type,
            "repo": repo_full_name,
            "status": "ignored",
            "details": "webhook event type not handled",
        }

        with self._state_lock():
            # Handle Pull Request events
            if event_type == "pull_request":
                pr_data = payload.get("pull_request")
                action = payload.get("action")
                if not pr_data or not action:
                    return {**processed_summary, "status": "skipped", "details": "missing pull_request data or action"}

                pr_number = pr_data.get("number")
                pr_branch = pr_data.get("head", {}).get("ref")
                pr_head_sha = pr_data.get("head", {}).get("sha")
                pr_state = pr_data.get("state") # open, closed, etc.
                pr_merged = pr_data.get("merged") # boolean

                pr_entry = self._find_pr_in_stacks_unlocked(
                    repo=repo_full_name, pr_number=pr_number, branch=pr_branch, head_sha=pr_head_sha
                )

                if pr_entry:
                    current_stack = pr_entry.pop("stack") # Remove the temporarily attached stack
                    _pr_stack.update_pr_state(
                        stack=current_stack, # Pass the full stack dictionary
                        pr_id=pr_entry["id"],
                        state=pr_state,
                        pr_number=pr_number,
                    )
                    
                    if action == "closed":
                        if pr_merged:
                            ungated_prs = _pr_stack.process_merge_event(current_stack, pr_entry["id"])
                            processed_summary.update({
                                "status": "pr_merged",
                                "details": f"PR {pr_number} merged in stack {pr_entry.get('stack_id')}",
                                "pr_id": pr_entry["id"],
                                "pr_number": pr_number,
                                "ungated_child_prs": [p["id"] for p in ungated_prs]
                            })
                        else:
                            _pr_stack.process_close_event(current_stack, pr_entry["id"])
                            processed_summary.update({
                                "status": "pr_closed",
                                "details": f"PR {pr_number} closed (not merged) in stack {pr_entry.get('stack_id')}",
                                "pr_id": pr_entry["id"],
                                "pr_number": pr_number,
                            })
                    else: # opened, reopened, synchronize, edited, ready_for_review, etc.
                        processed_summary.update({
                            "status": "pr_updated",
                            "details": f"PR {pr_number} {action} in stack {pr_entry.get('stack_id')}",
                            "pr_id": pr_entry["id"],
                            "pr_number": pr_number,
                        })
                    stacks = self._read_json_list(self.pr_stacks_path) # Re-read all stacks to find the one that contains `current_stack` and update it
                    for i, s in enumerate(stacks):
                        if s["id"] == current_stack["id"]:
                            stacks[i] = current_stack
                            break
                    self._write_json(self.pr_stacks_path, stacks) # Write back the modified stacks
                else:
                    processed_summary.update({
                        "status": "pr_not_in_stack",
                        "details": f"PR {pr_number} {action}, but not found in any existing stack. Manual intervention might be needed.",
                        "pr_number": pr_number,
                    })

                self.bus.emit(f"github.pr.{action}", processed_summary, source=source)
                return processed_summary

            # Handle Check Run events
            elif event_type == "check_run":
                check_run = payload.get("check_run")
                if not check_run:
                    return {**processed_summary, "status": "skipped", "details": "missing check_run data"}

                normalized_ci = normalize_github_ci_result(check_run)
                head_sha = normalized_ci.get("sha")
                pull_requests = check_run.get("pull_requests", []) # check_run can be linked to multiple PRs

                if not head_sha:
                    return {**processed_summary, "status": "skipped", "details": "check_run missing head_sha"}

                updated_prs: List[Dict[str, Any]] = []
                
                # Prioritize matching via linked pull_requests in the check_run payload
                if pull_requests:
                    for pr_link in pull_requests:
                        pr_number = pr_link.get("number")
                        pr_branch = pr_link.get("head", {}).get("ref")

                        pr_entry = self._find_pr_in_stacks_unlocked(
                            repo=repo_full_name, pr_number=pr_number, branch=pr_branch, head_sha=head_sha
                        )

                        if pr_entry:
                            current_stack = pr_entry.pop("stack") # Remove the temporarily attached stack
                            _pr_stack.update_pr_state(
                                stack=current_stack,
                                pr_id=pr_entry["id"],
                                ci_status=normalized_ci.get("state"),
                                pr_number=pr_number, # Ensure pr_number is set if it wasn't before
                            )
                            stacks = self._read_json_list(self.pr_stacks_path) # Re-read all stacks to find the one that contains `current_stack` and update it
                            for i, s in enumerate(stacks):
                                if s["id"] == current_stack["id"]:
                                    stacks[i] = current_stack
                                    break
                            self._write_json(self.pr_stacks_path, stacks)
                            updated_prs.append({
                                "pr_id": pr_entry["id"],
                                "pr_number": pr_number,
                                "stack_id": pr_entry["stack_id"],
                                "ci_state": normalized_ci.get("state"),
                            })
                        else:
                            print(f"INFO: Check run for PR {pr_number} ({pr_branch}) in {repo_full_name} received, but PR not found in any stack.", file=sys.stderr, flush=True)
                
                # If no linked PRs or if PRs were not found in stacks, try matching directly by branch/SHA
                if not updated_prs and check_run.get("head_branch"):
                    branch = check_run.get("head_branch")
                    pr_entry = self._find_pr_in_stacks_unlocked(
                        repo=repo_full_name, branch=branch, head_sha=head_sha
                    )
                    if pr_entry:
                        current_stack = pr_entry.pop("stack")
                        _pr_stack.update_pr_state(
                            stack=current_stack,
                            pr_id=pr_entry["id"],
                            ci_status=normalized_ci.get("state"),
                            pr_number=pr_entry.get("pr_number"),
                        )
                        stacks = self._read_json_list(self.pr_stacks_path) # Re-read all stacks to find the one that contains `current_stack` and update it
                        for i, s in enumerate(stacks):
                            if s["id"] == current_stack["id"]:
                                stacks[i] = current_stack
                                break
                        self._write_json(self.pr_stacks_path, stacks)
                        updated_prs.append({
                            "pr_id": pr_entry["id"],
                            "pr_number": pr_entry.get("pr_number"),
                            "stack_id": pr_entry.get("stack_id"),
                            "ci_state": normalized_ci.get("state"),
                        })
                    else:
                        print(f"INFO: Check run for branch {branch} ({head_sha}) in {repo_full_name} received, but no matching PR in any stack.", file=sys.stderr, flush=True)

                if updated_prs:
                    processed_summary.update({
                        "status": "ci_updated",
                        "details": f"CI status updated for {len(updated_prs)} PR(s)",
                        "ci_state": normalized_ci.get("state"),
                        "updated_prs": updated_prs,
                    })
                else:
                    processed_summary.update({
                        "status": "ci_no_matching_pr_in_stack",
                        "details": f"Check run for {head_sha} has no matching PR in any stack.",
                        "ci_state": normalized_ci.get("state"),
                    })

                self.bus.emit("github.check_run", processed_summary, source=source)
                return processed_summary

            self.bus.emit(f"github.webhook.unhandled.{event_type}", payload, source=source)
            return processed_summary
        
        return {
            "status": "unhandled_action",
            "reason": f"No specific handler for action_required: {action_required}",
            "task_id": task_id,
            "log_message": log_message,
        }

    # ------------------------------------------------------------------
    # Unsupervised stop / escalation policy
    # ------------------------------------------------------------------

    def evaluate_stop_policy(self) -> Dict[str, Any]:
        """Evaluate unsupervised run stop/escalation triggers.

        Reads thresholds from ``policy.triggers`` and compares against
        live state.  Returns a dict with ``stop_required``, a list of
        fired ``triggers``, and per-trigger detail so the caller can
        decide whether to halt the unsupervised run.

        If the policy is disabled (``unsupervised_stop_enabled`` is
        falsy) the method returns ``stop_required=False`` with an empty
        trigger list — fully backward compatible.
        """
        triggers_cfg = self.policy.triggers

        # Guard: if the stop policy is not enabled, return clean.
        if not triggers_cfg.get("unsupervised_stop_enabled", False):
            return {
                "stop_required": False,
                "policy_enabled": False,
                "triggers": [],
                "reason_codes": [],
            }

        tasks = self._read_json(self.tasks_path)
        open_bugs = self.list_bugs(status="open")
        open_blockers = self.list_blockers(status="open")

        fired: List[Dict[str, Any]] = []

        # --- Trigger 1: open bug count exceeds threshold ---------------
        max_bugs = int(triggers_cfg.get("stop_max_open_bugs", 0))
        if max_bugs > 0 and len(open_bugs) >= max_bugs:
            fired.append({
                "code": "bug_threshold_exceeded",
                "severity": "critical",
                "detail": f"open_bugs={len(open_bugs)} >= threshold={max_bugs}",
                "current": len(open_bugs),
                "threshold": max_bugs,
            })

        # --- Trigger 2: open blocker count exceeds threshold -----------
        max_blockers = int(triggers_cfg.get("stop_max_open_blockers", 0))
        if max_blockers > 0 and len(open_blockers) >= max_blockers:
            fired.append({
                "code": "blocker_growth_exceeded",
                "severity": "critical",
                "detail": f"open_blockers={len(open_blockers)} >= threshold={max_blockers}",
                "current": len(open_blockers),
                "threshold": max_blockers,
            })

        # --- Trigger 3: repeated validation failures per task ----------
        max_failures = int(triggers_cfg.get("stop_max_validation_failures_per_task", 0))
        if max_failures > 0:
            for task in tasks:
                fail_count = self._count_validation_failures(task)
                if fail_count >= max_failures:
                    fired.append({
                        "code": "repeated_validation_failure",
                        "severity": "critical",
                        "detail": (
                            f"task={task['id']} validation_failures={fail_count} "
                            f">= threshold={max_failures}"
                        ),
                        "task_id": task["id"],
                        "current": fail_count,
                        "threshold": max_failures,
                    })

        # --- Trigger 4: integrity mismatch (task count regression) -----
        if triggers_cfg.get("stop_on_integrity_mismatch", False):
            integrity = self._check_integrity_simple(tasks)
            if not integrity["ok"]:
                fired.append({
                    "code": "integrity_mismatch",
                    "severity": "critical",
                    "detail": "; ".join(integrity.get("warnings", ["integrity check failed"])),
                })

        # --- Trigger 5: deploy / source mismatch -----------------------
        # This trigger is evaluated by the MCP layer since it requires
        # server-level state (_runtime_source_consistency).  The engine
        # exposes a hook so the MCP layer can inject the result.

        stop_required = len(fired) > 0
        reason_codes = [t["code"] for t in fired]

        result: Dict[str, Any] = {
            "stop_required": stop_required,
            "policy_enabled": True,
            "triggers": fired,
            "reason_codes": reason_codes,
        }

        if stop_required:
            self.bus.emit(
                "stop_policy.triggered",
                {
                    "reason_codes": reason_codes,
                    "trigger_count": len(fired),
                    "triggers": fired,
                },
                source="orchestrator",
            )
            self.bus.append_audit({
                "category": "stop_policy",
                "action": "stop_triggered",
                "reason_codes": reason_codes,
                "trigger_count": len(fired),
            })

        return result

    def _count_validation_failures(self, task: Dict[str, Any]) -> int:
        """Count how many open bugs reference this task (proxy for validation failures)."""
        task_id = task.get("id", "")
        bugs = self._read_json_list(self.bugs_path)
        return sum(
            1 for bug in bugs
            if bug.get("source_task") == task_id and bug.get("status") == "open"
        )

    def _check_integrity_simple(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Lightweight integrity check: detect task count regression via audit."""
        current_count = len(tasks)
        max_seen = current_count
        warnings: List[str] = []

        for row in self.bus.read_audit(limit=200, tool_name="orchestrator_status", status="ok"):
            result = row.get("result", {})
            if not isinstance(result, dict):
                continue
            try:
                hist_count = int(result.get("task_count", 0))
            except Exception:
                continue
            if hist_count > max_seen:
                max_seen = hist_count

        if current_count < max_seen:
            warnings.append(
                f"task_count_regression: current={current_count} < historical_max={max_seen}"
            )

        return {"ok": len(warnings) == 0, "warnings": warnings}

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
        return str(self.get_roles().get("leader", self.policy.manager()))

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
        leader_instance_id = roles.get("leader_instance_id")
        if not isinstance(leader_instance_id, str) or not leader_instance_id.strip():
            leader_instance_id = f"{leader}#default"
        normalized_members = sorted(
            {
                item.strip()
                for item in members
                if isinstance(item, str) and item.strip() and item.strip() != leader
            }
        )
        return {
            "leader": leader,
            "leader_instance_id": leader_instance_id,
            "team_members": normalized_members,
            "default_leader": self.policy.manager(),
        }

    def set_role(
        self,
        agent: str,
        role: str,
        source: str,
        instance_id: Optional[str] = None,
        source_instance_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
                default_manager = str(self.policy.manager()).strip()
                recovery_allowed = (
                    bool(default_manager)
                    and source == default_manager
                    and current_leader != default_manager
                    and not self._leader_is_operational_for_project_locked(current_leader)
                )
                if not recovery_allowed:
                    raise ValueError(f"leader_mismatch: source={source}, current_leader={current_leader}")
            expected_leader_instance = str(current.get("leader_instance_id", "")).strip()
            provided_source_instance = str(source_instance_id or "").strip()
            if (
                source == current_leader
                and expected_leader_instance
                and provided_source_instance
                and provided_source_instance != expected_leader_instance
            ):
                raise ValueError(
                    "leader_instance_mismatch: "
                    f"source_instance={provided_source_instance}, current_leader_instance={expected_leader_instance}"
                )
            leader = current["leader"]
            leader_instance = str(current.get("leader_instance_id", "")).strip() or f"{leader}#default"
            team_members = set(current["team_members"])
            target = agent.strip()

            if normalized_role == "leader":
                leader = target
                requested_instance = str(instance_id or "").strip()
                if requested_instance:
                    leader_instance = requested_instance
                elif target == source and provided_source_instance:
                    leader_instance = provided_source_instance
                else:
                    leader_instance = self._resolve_agent_instance_id_unlocked(target)
                team_members.discard(target)
            else:
                if target == leader:
                    raise ValueError("current leader cannot be assigned as team_member")
                team_members.add(target)

            updated = {
                "leader": leader,
                "leader_instance_id": leader_instance or f"{leader}#default",
                "team_members": sorted(team_members),
            }
            self._write_json(self.roles_path, updated)
        self.bus.emit(
            "role.updated",
            {
                "agent": target,
                "role": normalized_role,
                "leader": leader,
                "leader_instance_id": leader_instance or f"{leader}#default",
                "team_members": sorted(team_members),
            },
            source=source,
        )
        return self.get_roles()

    def _normalize_task_type(self, task_type: Optional[str]) -> str:
        normalized = str(task_type or "standard").strip().lower()
        if normalized not in TASK_TYPES:
            raise ValueError(f"task_type must be one of: {', '.join(sorted(TASK_TYPES))}")
        return normalized

    def _normalize_task_delivery_profile(
        self,
        risk: Optional[str],
        test_plan: Optional[str],
        doc_impact: Optional[str],
    ) -> Dict[str, str]:
        allowed_risk = {"low", "medium", "high"}
        allowed_test_plan = {"smoke", "targeted", "full"}
        allowed_doc_impact = {"none", "readme", "runbook", "roadmap"}

        normalized_risk = str(risk or "medium").strip().lower()
        normalized_test_plan = str(test_plan or "targeted").strip().lower()
        normalized_doc_impact = str(doc_impact or "none").strip().lower()

        if normalized_risk not in allowed_risk:
            raise ValueError("risk must be one of: low, medium, high")
        if normalized_test_plan not in allowed_test_plan:
            raise ValueError("test_plan must be one of: smoke, targeted, full")
        if normalized_doc_impact not in allowed_doc_impact:
            raise ValueError("doc_impact must be one of: none, readme, runbook, roadmap")

        return {
            "risk": normalized_risk,
            "test_plan": normalized_test_plan,
            "doc_impact": normalized_doc_impact,
        }

    def register_agent(self, agent: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._state_lock():
            agents = self._read_json(self.agents_path)
            if not isinstance(agents, dict):
                agents = {}
            entry = agents.get(agent, {})
            entry["agent"] = agent
            entry["status"] = "active"
            existing_metadata = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
            incoming_metadata = metadata if isinstance(metadata, dict) else {}
            entry["metadata"] = self._normalize_agent_metadata(agent=agent, metadata=incoming_metadata, existing=existing_metadata)
            entry["last_seen"] = self._now()
            agents[agent] = entry
            self._write_json(self.agents_path, agents)
            self._record_agent_instance_locked(agent=agent, entry=entry)
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
                entry["metadata"] = self._normalize_agent_metadata(agent=agent, metadata=merged)
            else:
                entry["metadata"] = self._normalize_agent_metadata(
                    agent=agent,
                    metadata=entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {},
                )
            entry["last_seen"] = self._now()
            agents[agent] = entry
            self._write_json(self.agents_path, agents)
            self._record_agent_instance_locked(agent=agent, entry=entry)
        self.bus.emit("agent.heartbeat", {"agent": agent}, source=agent)
        return entry

    def connect_to_leader(
        self,
        agent: str,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "idle",
        announce: bool = True,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        explicit_role_provided = "role" in metadata_payload and bool(str(metadata_payload.get("role", "")).strip())

        details = dict(metadata_payload)
        details.setdefault("role", "team_member")
        details["status"] = status
        requested_role = str(details.get("role", "team_member")).strip().lower()
        details = self._normalize_agent_metadata(agent=agent, metadata=details)
        agent_instance_id = str(details.get("instance_id", "")).strip() or f"{agent}#default"
        roles = self.get_roles()
        manager = str(roles.get("leader", self.policy.manager()))
        leader_instance_id = str(roles.get("leader_instance_id", "")).strip() or f"{manager}#default"
        manager_same_instance = agent == manager and agent_instance_id == leader_instance_id
        manager_default_placeholder = leader_instance_id == f"{manager}#default"
        if agent == manager and manager_default_placeholder and requested_role != "manager":
            # Before manager instance is pinned, treat same-agent non-manager connects
            # as leader self-connect attempts and block them.
            manager_same_instance = True
        if manager_same_instance and requested_role != "manager" and not explicit_role_provided:
            # Default manager self-connects should not require callers to pass role=manager.
            requested_role = "manager"
            details["role"] = "manager"

        self.register_agent(agent=agent, metadata=details)
        # Re-assert full identity metadata on heartbeat so same-agent concurrent
        # sessions cannot leave stale project/identity fields in the singleton
        # agents record between register and connect verification.
        entry = self.heartbeat(agent=agent, metadata=details)
        effective_source = source if isinstance(source, str) and source.strip() else agent

        identity = self._identity_snapshot(entry=entry, stale_after_seconds=self._heartbeat_timeout_seconds())
        verification = {
            "verified": bool(identity.get("verified")),
            "same_project": bool(identity.get("same_project")),
            "reason": identity.get("reason"),
        }
        if effective_source != agent:
            verification["verified"] = False
            verification["reason"] = "source_agent_mismatch"
        if manager_same_instance and requested_role != "manager":
            verification["verified"] = False
            verification["reason"] = "manager_role_mismatch"
        if agent != manager and requested_role == "manager":
            verification["verified"] = False
            verification["reason"] = "non_manager_declared_manager_role"
        connected = bool(verification.get("verified")) and (
            bool(verification.get("same_project")) or self._allow_cross_project_agents()
        )
        if connected and requested_role == "manager" and agent == manager:
            with self._state_lock():
                current_roles = self.get_roles()
                current_roles["leader_instance_id"] = agent_instance_id
                self._write_json(
                    self.roles_path,
                    {
                        "leader": str(current_roles.get("leader", manager)),
                        "leader_instance_id": agent_instance_id,
                        "team_members": list(current_roles.get("team_members", [])),
                    },
                )

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
        is_manager_connect = manager_same_instance or requested_role == "manager"
        auto_claimed = (
            self.claim_next_task(owner=agent, instance_id=str(details.get("instance_id", "")).strip() or None)
            if connected and not is_manager_connect
            else None
        )
        reason = verification.get("reason")
        reason_message = self._connect_to_leader_reason_message(
            reason=str(reason) if reason is not None else "",
            agent=agent,
            manager=manager,
            requested_role=requested_role,
            source=effective_source,
        )

        return {
            "connected": connected,
            "agent": agent,
            "manager": manager,
            "leader_instance_id": leader_instance_id,
            "entry": entry,
            "identity": identity,
            "verified": verification.get("verified"),
            "reason": reason,
            "reason_message": reason_message,
            "auto_claimed_task": auto_claimed,
            "next": [
                f"orchestrator_poll_events(agent={agent}, timeout_ms=120000)",
                f"orchestrator_claim_next_task(agent={agent})",
            ],
        }

    @staticmethod
    def _connect_to_leader_reason_message(
        reason: str,
        agent: str,
        manager: str,
        requested_role: str,
        source: str,
    ) -> str:
        if reason == "verified_identity":
            return "Agent identity verified for this project."
        if reason == "verified_identity_cross_project":
            return "Agent identity verified for cross-project mode."
        if reason == "manager_role_mismatch" and agent == manager:
            return (
                f"Agent '{agent}' is currently leader and cannot attach as wingman/team_member to itself. "
                f"Switch leader to another active agent, then retry connect_to_leader for '{agent}'."
            )
        if reason == "source_agent_mismatch":
            return f"Source '{source}' does not match connecting agent '{agent}'."
        if reason == "non_manager_declared_manager_role":
            return (
                f"Agent '{agent}' declared manager role while current leader is '{manager}'. "
                "Use team_member/wingman role for non-leader connects."
            )
        if reason.startswith("missing_identity_fields"):
            return "Identity metadata is incomplete; provide required identity fields."
        if reason == "project_mismatch":
            return "Agent identity does not match this project root/cwd."
        if reason == "stale_heartbeat":
            return "Agent heartbeat is stale; refresh with register/heartbeat and retry."
        if reason == "not_registered":
            return "Agent is not registered; call register_agent then retry connect_to_leader."
        return "Connection not verified."

    def _resolve_agent_instance_id_unlocked(self, agent: str) -> str:
        current = self._current_agent_instance_id_unlocked(agent)
        if current and current != f"{agent}#default":
            return current
        instances = self._read_json(self.agent_instances_path)
        if isinstance(instances, dict):
            latest: Optional[Dict[str, Any]] = None
            for entry in instances.values():
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("agent", "")).strip() != agent:
                    continue
                if latest is None:
                    latest = entry
                    continue
                if str(entry.get("last_seen", "")) > str(latest.get("last_seen", "")):
                    latest = entry
            if isinstance(latest, dict):
                candidate = str(latest.get("instance_id", "")).strip()
                if candidate:
                    return candidate
        return f"{agent}#default"

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
            if not bool(identity.get("verified")):
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
                "superseded": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "superseded"
                ),
                "archived": sum(
                    1
                    for task in tasks
                    if task.get("owner") == item.get("agent") and task.get("status") == "archived"
                ),
            }
            results.append(item)

        if stale_changed:
            self._write_json(self.stale_notices_path, stale_notices)
        results.sort(key=lambda x: x.get("agent", ""))
        return results

    def list_agent_instances(
        self,
        active_only: bool = False,
        stale_after_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        stale_after = stale_after_seconds if stale_after_seconds is not None else self._heartbeat_timeout_seconds()
        instances = self._read_json(self.agent_instances_path)
        if not isinstance(instances, dict):
            return []
        now = datetime.now(timezone.utc)
        results: List[Dict[str, Any]] = []

        for _, raw in instances.items():
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            entry = {
                "agent": item.get("agent"),
                "metadata": item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
                "last_seen": item.get("last_seen"),
                "status": item.get("status", "unknown"),
            }
            identity = self._identity_snapshot(entry=entry, stale_after_seconds=stale_after)
            age = self._age_seconds(str(item.get("last_seen")), now=now) if item.get("last_seen") else None
            computed_status = "active" if age is not None and age <= stale_after else "offline"
            if not bool(identity.get("verified")):
                computed_status = "offline"
            item["status"] = computed_status
            item["age_seconds"] = age
            item["identity"] = identity
            item["instance_id"] = identity.get("instance_id")
            item["agent_name"] = item.get("agent")
            item["role"] = str(item.get("metadata", {}).get("role", "")).strip().lower() or None
            item["project_root"] = identity.get("project_root")
            item["current_task_id"] = item.get("metadata", {}).get("current_task_id")
            if active_only and computed_status != "active":
                continue
            results.append(item)

        results.sort(key=lambda x: (str(x.get("agent_name", "")), str(x.get("instance_id", ""))))
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

    def compact_events(self, retention_limit: Optional[int] = None) -> Dict[str, Any]:
        """Compact the event bus: archive old events and adjust agent cursors.

        Uses ``policy.triggers.event_retention_limit`` (default 500) unless
        *retention_limit* is passed explicitly.  Agent cursors are shifted so
        that every connected agent continues to point at the correct event
        after compaction — no events are lost for any agent whose cursor is
        still within the retained window.
        """
        if retention_limit is None:
            retention_limit = int(self.policy.triggers.get("event_retention_limit", 500))

        with self._state_lock():
            result = self.bus.compact_events(retention_limit=retention_limit)
            offset_adj = result.get("offset_adjustment", 0)

            if offset_adj > 0:
                cursors = self._read_json(self.cursors_path)
                if isinstance(cursors, dict):
                    for agent in cursors:
                        cursors[agent] = max(0, int(cursors[agent]) - offset_adj)
                    self._write_json(self.cursors_path, cursors)
                    result["cursors_adjusted"] = len(cursors)

        if result.get("archived", 0) > 0:
            self.bus.emit(
                "events.compacted",
                {
                    "archived": result["archived"],
                    "retained": result["retained"],
                    "offset_adjustment": result["offset_adjustment"],
                },
                source="orchestrator",
            )

        return result

    def _close_bugs_for_task(self, task_id: str, note: str) -> None:
        bugs = self._read_json_list(self.bugs_path)
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
        bugs = self._read_json_list(self.bugs_path)
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

        # Attempt to create a GitHub issue for the newly opened bug
        self._create_github_issue_from_bug(bug)

        return bug

    def _create_github_issue_from_bug(
        self,
        bug: Dict[str, Any],
        repo_full_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a GitHub issue from a bug record.

        Uses :func:`build_github_issue_payload` for payload generation and
        :func:`post_github_issue` to call the GitHub API.  Falls back to a
        dry-run when credentials are missing or the API call fails.
        """
        bug_id = bug.get("id", "UNKNOWN_BUG")

        repo = repo_full_name or os.getenv("GITHUB_REPOSITORY")
        if not repo:
            print(
                "WARNING: GITHUB_REPOSITORY environment variable not set and no repo_full_name provided. "
                "Cannot create GitHub issue.",
                file=sys.stderr,
                flush=True,
            )
            return {
                "status": "skipped",
                "reason": "GITHUB_REPOSITORY missing",
                "bug_id": bug_id,
            }

        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            print(
                "WARNING: GITHUB_TOKEN environment variable not set. Cannot perform GitHub API actions.",
                file=sys.stderr,
                flush=True,
            )
            return {
                "status": "skipped",
                "reason": "GITHUB_TOKEN missing",
                "bug_id": bug_id,
            }

        payload = build_github_issue_payload(bug)
        issue_title = payload["title"]

        # Try the real GitHub API; fall back to dry-run on failure.
        try:
            api_resp = post_github_issue(repo, github_token, payload)
            issue_number = api_resp.get("number", 0)
            issue_url = api_resp.get("html_url", f"https://github.com/{repo}/issues/{issue_number}")
            action = "github_issue_created"
        except Exception as exc:
            print(
                f"WARNING: GitHub API call failed for bug {bug_id}: {exc}. "
                "Recording as dry-run.",
                file=sys.stderr,
                flush=True,
            )
            issue_number = int(uuid.uuid4().hex[:8], 16) % 10000 + 1
            issue_url = f"https://github.com/{repo}/issues/{issue_number}"
            action = "dry_run_github_issue_creation"

        with self._state_lock():
            bugs = self._read_json_list(self.bugs_path)
            for b in bugs:
                if b["id"] == bug_id:
                    b["github_issue"] = {
                        "repo": repo,
                        "issue_number": issue_number,
                        "url": issue_url,
                        "title": issue_title,
                        "status": "open",
                        "created_at": self._now(),
                    }
                    b["updated_at"] = self._now()
                    break
            self._write_json(self.bugs_path, bugs)

        result = {
            "status": "success",
            "action": action,
            "bug_id": bug_id,
            "repo": repo,
            "issue_number": issue_number,
            "issue_url": issue_url,
            "issue_title": issue_title,
        }
        self.bus.emit("bug.github_issue_created", result, source="orchestrator")
        return result

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

        review_gate = report.get("review_gate")
        if review_gate is not None and not isinstance(review_gate, dict):
            raise ValueError("review_gate must be an object when provided")
        if isinstance(review_gate, dict):
            self._normalize_review_gate(review_gate)

        comprehension_summary = report.get("comprehension_summary")
        if comprehension_summary is not None:
            self._validate_comprehension_summary(comprehension_summary)

        ci_logs = report.get("ci_logs")
        if ci_logs is not None:
            if not isinstance(ci_logs, list):
                raise ValueError("ci_logs must be an array")
            for i, log_url in enumerate(ci_logs):
                if not isinstance(log_url, str) or not log_url.strip():
                    raise ValueError(f"ci_logs[{i}] must be a non-empty string")

        ci_artifacts = report.get("ci_artifacts")
        if ci_artifacts is not None:
            if not isinstance(ci_artifacts, list):
                raise ValueError("ci_artifacts must be an array")
            for i, artifact in enumerate(ci_artifacts):
                if not isinstance(artifact, dict):
                    raise ValueError(f"ci_artifacts[{i}] must be an object")
                if not isinstance(artifact.get("name"), str) or not artifact["name"].strip():
                    raise ValueError(f"ci_artifacts[{i}].name must be a non-empty string")
                if not isinstance(artifact.get("url"), str) or not artifact["url"].strip():
                    raise ValueError(f"ci_artifacts[{i}].url must be a non-empty string")

    @staticmethod
    def _validate_comprehension_summary(summary: Any) -> None:
        """Validate a structured comprehension summary artifact."""
        if not isinstance(summary, dict):
            raise ValueError("comprehension_summary must be an object")
        required_keys = {"modules", "patterns", "dependencies"}
        missing = sorted(required_keys - set(summary))
        if missing:
            raise ValueError(f"comprehension_summary missing required fields: {', '.join(missing)}")
        for key in ("modules", "patterns", "dependencies"):
            value = summary.get(key)
            if not isinstance(value, list):
                raise ValueError(f"comprehension_summary.{key} must be an array")
        # Validate module entries
        for i, mod in enumerate(summary["modules"]):
            if not isinstance(mod, dict):
                raise ValueError(f"comprehension_summary.modules[{i}] must be an object")
            if not isinstance(mod.get("name"), str) or not mod["name"].strip():
                raise ValueError(f"comprehension_summary.modules[{i}].name must be a non-empty string")
            if not isinstance(mod.get("responsibility"), str):
                raise ValueError(f"comprehension_summary.modules[{i}].responsibility must be a string")

    def _normalize_review_gate(self, review_gate: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(review_gate, dict):
            raise ValueError("review_gate must be an object")
        normalized: Dict[str, Any] = {}
        required = bool(review_gate.get("required", False))
        normalized["required"] = required

        status = str(review_gate.get("status", "")).strip().lower()
        allowed_statuses = {"pending", "approved", "rejected", "waived", ""}
        if status not in allowed_statuses:
            raise ValueError("review_gate.status must be one of pending|approved|rejected|waived")
        if status:
            normalized["status"] = status
        elif required:
            normalized["status"] = "pending"

        for key in ("reviewer_agent", "reviewer_role", "reviewer_instance_id", "reviewer_notes", "review_commit_sha"):
            raw = review_gate.get(key)
            if raw is None:
                continue
            if not isinstance(raw, str):
                raise ValueError(f"review_gate.{key} must be a string")
            value = raw.strip()
            if value:
                normalized[key] = value

        reviewed_at = review_gate.get("reviewed_at")
        if reviewed_at is not None:
            if not isinstance(reviewed_at, str) or not reviewed_at.strip():
                raise ValueError("review_gate.reviewed_at must be a non-empty string")
            normalized["reviewed_at"] = reviewed_at.strip()

        return normalized

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
        allow_cross_project = self._allow_cross_project_agents()
        if verification.get("verified") and not same_project and not allow_cross_project:
            verification["verified"] = False
            verification["reason"] = "project_mismatch"
        elif verification.get("verified") and not same_project and allow_cross_project:
            verification["reason"] = "verified_identity_cross_project"

        return {
            "agent_id": entry.get("agent"),
            "instance_id": metadata.get("instance_id"),
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

    def _normalize_agent_metadata(
        self,
        agent: str,
        metadata: Optional[Dict[str, Any]],
        existing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        if isinstance(existing, dict):
            merged.update(existing)
        if isinstance(metadata, dict):
            merged.update(metadata)

        instance_id = str(merged.get("instance_id", "")).strip()
        if not instance_id:
            session_id = str(merged.get("session_id", "")).strip()
            connection_id = str(merged.get("connection_id", "")).strip()
            if session_id:
                instance_id = session_id
            elif connection_id:
                instance_id = connection_id
            else:
                instance_id = f"{agent}#default"
        merged["instance_id"] = instance_id
        return merged

    def _current_agent_instance_id_unlocked(self, agent: str) -> str:
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            return f"{agent}#default"
        entry = agents.get(agent, {})
        metadata = entry.get("metadata", {}) if isinstance(entry, dict) else {}
        normalized = self._normalize_agent_metadata(agent=agent, metadata=metadata if isinstance(metadata, dict) else {})
        return str(normalized.get("instance_id", "")).strip() or f"{agent}#default"

    def _lease_ttl_seconds(self) -> int:
        raw = self.policy.triggers.get("lease_ttl_seconds", 300)
        try:
            ttl = int(raw)
        except Exception:
            ttl = 300
        return max(30, ttl)

    def _timestamp_plus_seconds(self, seconds: int) -> str:
        return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + max(0, int(seconds)), tz=timezone.utc).isoformat()

    def _lease_expired(self, lease: Dict[str, Any]) -> bool:
        expires_at = str(lease.get("expires_at", "")).strip()
        if not expires_at:
            return True
        try:
            return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
        except Exception:
            return True

    def _issue_task_lease_unlocked(self, task: Dict[str, Any], owner: str, owner_instance_id: str) -> None:
        now = self._now()
        ttl = self._lease_ttl_seconds()
        task["lease"] = {
            "lease_id": f"LEASE-{uuid.uuid4().hex[:8]}",
            "owner": owner,
            "owner_instance_id": owner_instance_id or f"{owner}#default",
            "issued_at": now,
            "renewed_at": now,
            "expires_at": self._timestamp_plus_seconds(ttl),
            "ttl_seconds": ttl,
        }

    def _instance_record_key(self, agent: str, instance_id: str) -> str:
        return f"{agent}::{instance_id}"

    def _record_agent_instance_locked(self, agent: str, entry: Dict[str, Any]) -> None:
        instances = self._read_json(self.agent_instances_path)
        if not isinstance(instances, dict):
            instances = {}
        metadata = entry.get("metadata", {}) if isinstance(entry.get("metadata"), dict) else {}
        normalized = self._normalize_agent_metadata(agent=agent, metadata=metadata)
        instance_id = str(normalized.get("instance_id", "")).strip() or f"{agent}#default"
        key = self._instance_record_key(agent=agent, instance_id=instance_id)
        instances[key] = {
            "agent": agent,
            "instance_id": instance_id,
            "metadata": normalized,
            "status": entry.get("status", "active"),
            "last_seen": entry.get("last_seen", self._now()),
            "updated_at": self._now(),
        }
        self._write_json(self.agent_instances_path, instances)

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

    def _allow_cross_project_agents(self) -> bool:
        return bool(self.policy.triggers.get("allow_cross_project_agents", False))

    def _normalize_task_tags(
        self,
        tags: Optional[Any],
        project_name: Optional[str] = None,
        workstream: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[str]:
        items: List[str] = []
        if isinstance(tags, list):
            for item in tags:
                if isinstance(item, str):
                    cleaned = item.strip().lower()
                    if cleaned:
                        items.append(cleaned)
        elif isinstance(tags, str):
            cleaned = tags.strip().lower()
            if cleaned:
                items.append(cleaned)

        if project_name:
            pn = str(project_name).strip().lower()
            if pn:
                items.append(f"project:{pn}")
        if workstream:
            ws = str(workstream).strip().lower()
            if ws:
                items.append(f"workstream:{ws}")
        if team_id:
            tid = str(team_id).strip().lower()
            if tid:
                items.append(f"team:{tid}")

        return sorted(set(items))

    def _agent_project_scope_unlocked(self, agent: str) -> Dict[str, Any]:
        root = self.root
        name = self.root.name
        agents = self._read_json(self.agents_path)
        if isinstance(agents, dict):
            entry = agents.get(agent, {})
            metadata = entry.get("metadata", {}) if isinstance(entry, dict) else {}
            if isinstance(metadata, dict):
                project_root_raw = str(metadata.get("project_root", "")).strip()
                cwd_raw = str(metadata.get("cwd", "")).strip()
                project_name_raw = str(metadata.get("project_name", "")).strip()
                resolved = self._safe_resolve(project_root_raw or cwd_raw)
                if resolved is not None:
                    root = resolved
                    name = project_name_raw or resolved.name
                elif project_name_raw:
                    name = project_name_raw
        return {"project_root": root, "project_name": name}

    def _task_matches_project_scope(
        self,
        task: Dict[str, Any],
        project_root: Optional[Path],
        project_name: str,
    ) -> bool:
        if not isinstance(task, dict):
            return False
        project_root_raw = str(task.get("project_root", "")).strip()
        project_name_raw = str(task.get("project_name", "")).strip()
        if not project_root_raw and not project_name_raw:
            # Legacy tasks predate explicit task-level project tags.
            return True
        if project_root_raw:
            resolved = self._safe_resolve(project_root_raw)
            if resolved is None or (project_root is not None and resolved != project_root):
                return False
        if project_name_raw and project_name and project_name_raw != project_name:
            return False
        return True

    def _assert_task_project_scope(
        self,
        task: Dict[str, Any],
        operation: str,
        project_root: Optional[Path],
        project_name: str,
    ) -> None:
        if self._task_matches_project_scope(task, project_root=project_root, project_name=project_name):
            return
        raise ValueError(
            "task_wrong_project: "
            f"task_id={task.get('id', '')} operation={operation} "
            f"task_project_root={task.get('project_root', '<missing>')} "
            f"task_project_name={task.get('project_name', '<missing>')} "
            f"current_project_root={project_root} current_project_name={project_name}"
        )

    def _task_is_same_project(self, task: Dict[str, Any]) -> bool:
        return self._task_matches_project_scope(task, project_root=self.root, project_name=self.root.name)

    def _assert_task_same_project(self, task: Dict[str, Any], operation: str) -> None:
        self._assert_task_project_scope(
            task=task,
            operation=operation,
            project_root=self.root,
            project_name=self.root.name,
        )

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
            return bool(identity_complete) and (
                bool(identity.get("same_project")) or self._allow_cross_project_agents()
            )

    def _leader_is_operational_for_project_locked(self, leader: str) -> bool:
        if not isinstance(leader, str) or not leader.strip():
            return False
        agents = self._read_json(self.agents_path)
        if not isinstance(agents, dict):
            return False
        entry = agents.get(leader)
        if not isinstance(entry, dict):
            return False
        stale_after = self._heartbeat_timeout_seconds()
        identity = self._identity_snapshot(entry=entry, stale_after_seconds=stale_after)
        return bool(identity.get("verified")) and (
            bool(identity.get("same_project")) or self._allow_cross_project_agents()
        )

    def _assert_agent_operational(self, agent: str) -> None:
        if not self._agent_is_operational(agent):
            raise ValueError(f"agent_not_operational_or_wrong_project: {agent}")

    def _read_json(self, path: Path) -> Any:
        key = str(path)
        try:
            mtime_ns = path.stat().st_mtime_ns
        except FileNotFoundError:
            self._json_cache.pop(key, None)
            return []
        cached = self._json_cache.get(key)
        if cached is not None and cached[0] == mtime_ns:
            return copy.deepcopy(cached[1])
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        self._json_cache[key] = (mtime_ns, data)
        return copy.deepcopy(data)

    def _ensure_list_file(self, path: Path) -> List[Dict[str, Any]]:
        data = self._read_json(path)
        if isinstance(data, list):
            return data
        repaired: List[Dict[str, Any]] = []
        self._write_json(path, repaired)
        try:
            self.bus.append_audit(
                {
                    "category": "state_repair",
                    "path": str(path),
                    "action": "coerce_to_empty_list",
                    "previous_type": type(data).__name__,
                }
            )
        except Exception:
            pass
        return repaired

    def _read_json_list(self, path: Path) -> List[Dict[str, Any]]:
        data = self._read_json(path)
        if isinstance(data, list):
            return data
        repaired: List[Dict[str, Any]] = []
        self._write_json(path, repaired)
        try:
            self.bus.append_audit(
                {
                    "category": "state_repair",
                    "path": str(path),
                    "action": "coerce_to_empty_list",
                    "previous_type": type(data).__name__,
                    "via": "_read_json_list",
                }
            )
        except Exception:
            pass
        return repaired

    def _write_tasks_json(self, tasks: Any) -> None:
        """Write tasks.json with append-only cardinality protection.

        By design, tasks are not deleted from state/tasks.json through normal MCP
        flows; they only change status. A shrinking task list usually indicates a
        stale snapshot overwrite or manual corruption. Refuse the write unless an
        explicit escape hatch is set.
        """
        allow_shrink = os.getenv("ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if not allow_shrink and isinstance(tasks, list):
            try:
                current = self._read_json(self.tasks_path)
            except Exception:
                current = None
            if isinstance(current, list) and len(tasks) < len(current):
                try:
                    self.bus.append_audit(
                        {
                            "category": "state_guard",
                            "path": str(self.tasks_path),
                            "action": "reject_task_count_shrink",
                            "existing_count": len(current),
                            "attempted_count": len(tasks),
                        }
                    )
                except Exception:
                    pass
                raise RuntimeError(
                    f"refusing_tasks_json_shrink: existing_count={len(current)} attempted_count={len(tasks)} "
                    "set ORCHESTRATOR_ALLOW_TASK_COUNT_SHRINK=1 to override intentionally"
                )
        self._write_json(self.tasks_path, tasks)
        self._touch_wakeup_signals(tasks)

    def _touch_wakeup_signals(self, tasks: Any = None) -> None:
        """Touch per-agent wakeup signal files so event-driven loops can detect changes.

        Creates/updates state/.wakeup-{agent} for each agent that owns an
        assigned or bug_open task.  Workers using --event-driven watch these
        files instead of polling on a timer.

        Accepts an optional *tasks* list to avoid re-reading from disk when
        called immediately after a write.
        """
        try:
            if tasks is None:
                tasks = self._read_json(self.tasks_path)
            if not isinstance(tasks, list):
                return
            agents_with_work: set = set()
            for t in tasks:
                if str(t.get("status", "")).strip().lower() in {"assigned", "bug_open"}:
                    owner = str(t.get("owner", "")).strip()
                    if owner:
                        agents_with_work.add(owner)
            for agent in agents_with_work:
                signal_path = self.state_dir / f".wakeup-{agent}"
                signal_path.write_text(self._now(), encoding="utf-8")
        except Exception:
            pass  # Best-effort; never block task mutations

    def _write_json(self, path: Path, value: Any) -> None:
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
        # Invalidate cache so next _read_json re-reads from disk.
        self._json_cache.pop(str(path), None)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
