from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Iterator, Optional, Tuple

try:
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None


class EventBus:
    """Append-only JSONL event bus for local multi-agent coordination."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.events_path = root / "events.jsonl"
        self.audit_path = root / "audit.jsonl"
        self.commands_dir = root / "commands"
        self.reports_dir = root / "reports"

        self.root.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._events_lock = root / ".events.lock"
        self._audit_lock = root / ".audit.lock"
        if fcntl is None:
            print(
                "WARNING: fcntl unavailable; file locking disabled. Multi-process safety is degraded.",
                file=sys.stderr,
                flush=True,
            )

    @contextmanager
    def _file_lock(self, path: Path, exclusive: bool = True) -> Iterable[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as fh:
            if fcntl is not None:
                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(fh.fileno(), mode)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
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
    def _lock_for(path: Path) -> Path:
        return path.parent / f".{path.name}.lock"

    def emit(self, event_type: str, payload: Dict[str, Any], source: str) -> Dict[str, Any]:
        event = {
            "event_id": f"EVT-{uuid.uuid4().hex[:10]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "source": source,
            "payload": payload,
        }
        with self._file_lock(self._events_lock):
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return event

    def iter_events(self) -> Iterable[Dict[str, Any]]:
        if not self.events_path.exists():
            return []

        events = []
        with self._file_lock(self._events_lock, exclusive=False):
            with self.events_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        # Skip malformed lines instead of failing all consumers.
                        continue
        return events

    def poll_events(self, timeout_ms: int = 0) -> Iterable[Dict[str, Any]]:
        """Poll events, optionally waiting for timeout if no events exist yet."""
        if timeout_ms <= 0:
            return self.iter_events()

        deadline = time.time() + (timeout_ms / 1000.0)
        while True:
            events = list(self.iter_events())
            if events:
                return events
            if time.time() >= deadline:
                return events
            time.sleep(0.1)

    def _count_lines(self, path: Path, lock_path: Path) -> int:
        if not path.exists():
            return 0
        count = 0
        with self._file_lock(lock_path, exclusive=False):
            with path.open("r", encoding="utf-8") as fh:
                for _ in fh:
                    count += 1
        return count

    def wait_for_event_index(self, start: int, timeout_ms: int = 0) -> None:
        if timeout_ms <= 0:
            return
        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            if self._count_lines(self.events_path, self._events_lock) > max(0, int(start)):
                return
            time.sleep(0.1)

    def iter_events_from(self, start: int = 0) -> Iterator[Tuple[int, Dict[str, Any]]]:
        if not self.events_path.exists():
            return iter(())

        def _gen() -> Iterator[Tuple[int, Dict[str, Any]]]:
            idx = 0
            with self._file_lock(self._events_lock, exclusive=False):
                with self.events_path.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        if idx < start:
                            idx += 1
                            continue
                        line = raw.strip()
                        if not line:
                            idx += 1
                            continue
                        try:
                            event = json.loads(line)
                        except Exception:
                            idx += 1
                            continue
                        yield idx, event
                        idx += 1

        return _gen()

    def write_command(self, task_id: str, command: Dict[str, Any]) -> Path:
        path = self.commands_dir / f"{task_id}.json"
        lock = self._lock_for(path)
        with self._file_lock(lock):
            self._atomic_write_json(path, command)
        return path

    def write_report(self, task_id: str, report: Dict[str, Any]) -> Path:
        path = self.reports_dir / f"{task_id}.json"
        lock = self._lock_for(path)
        with self._file_lock(lock):
            self._atomic_write_json(path, report)
        return path

    def read_report(self, task_id: str) -> Optional[Dict[str, Any]]:
        path = self.reports_dir / f"{task_id}.json"
        if not path.exists():
            return None

        lock = self._lock_for(path)
        with self._file_lock(lock, exclusive=False):
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

    def append_audit(self, record: Dict[str, Any]) -> Dict[str, Any]:
        entry = dict(record)
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        with self._file_lock(self._audit_lock):
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return entry

    def read_audit(
        self,
        limit: int = 100,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Iterable[Dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        rows: Deque[Dict[str, Any]] | list[Dict[str, Any]]
        if limit > 0:
            rows = deque(maxlen=limit)
        else:
            rows = []
        with self._file_lock(self._audit_lock, exclusive=False):
            with self.audit_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if tool_name and item.get("tool") != tool_name:
                        continue
                    if status and item.get("status") != status:
                        continue
                    rows.append(item)
        if isinstance(rows, deque):
            return list(rows)
        return rows
