from __future__ import annotations

import gzip
import json
import logging
import os
import select
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

try:
    import inotify_simple
except ImportError:
    inotify_simple = None

logger = logging.getLogger("orchestrator.bus")


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

    @staticmethod
    def _lock_for(path: Path) -> Path:
        return path.parent / f".{path.name}.lock"

    # Fallback sleep interval when kqueue/inotify is unavailable.
    _POLL_FALLBACK_SLEEP = 0.5

    def _wait_for_file_change(self, path: Path, timeout_sec: float) -> bool:
        """Wait for *path* to be modified using kqueue, falling back to sleep.

        Returns True if a change was detected (or assumed on fallback),
        False on timeout.
        """
        if timeout_sec <= 0:
            return False

        # 1. Try kqueue for BSD/macOS
        if hasattr(select, "kqueue") and path.exists():
            fd = -1
            kq = None
            try:
                fd = os.open(str(path), os.O_RDONLY)
                kq = select.kqueue()
                ev = select.kevent(
                    fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    # Watch for writes and attribute changes (e.g., size changes)
                    # KQ_NOTE_EXTEND is important for files being appended to
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB,
                )
                events = kq.control([ev], 1, timeout_sec)
                return len(events) > 0
            except OSError as e:
                # Log the error but fall through to other mechanisms
                logger.debug("kqueue failed: %s", e)
            finally:
                if kq is not None:
                    kq.close()
                if fd >= 0:
                    os.close(fd)

        # 2. Try inotify for Linux
        if inotify_simple is not None and sys.platform.startswith("linux") and path.exists():
            ino = None
            try:
                ino = inotify_simple.INotify()
                # Watch the file for modify (IN_MODIFY) and close-write (IN_CLOSE_WRITE) events.
                # IN_ATTRIB for metadata changes
                watch_flags = (
                    inotify_simple.flags.MODIFY
                    | inotify_simple.flags.CLOSE_WRITE
                    | inotify_simple.flags.ATTRIB
                )
                ino.add_watch(str(path), watch_flags)

                # Use select to wait for events on the inotify file descriptor
                rlist, _, _ = select.select([ino.fd], [], [], timeout_sec)
                return bool(rlist) # If rlist is not empty, an event occurred

            except Exception as e:
                logger.debug("inotify failed: %s", e)
            finally:
                if ino is not None:
                    ino.close()

        # 3. Fallback: sleep for min(remaining, _POLL_FALLBACK_SLEEP) and assume possible change.
        time.sleep(min(timeout_sec, self._POLL_FALLBACK_SLEEP))
        return True

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
                try:
                    os.fsync(fh.fileno())
                except OSError as e:
                    logger.warning("event fsync failed: %s", e)
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
            remaining = deadline - time.time()
            if remaining <= 0:
                return events
            self._wait_for_file_change(self.events_path, remaining)

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
        while True:
            if self._count_lines(self.events_path, self._events_lock) > max(0, int(start)):
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            self._wait_for_file_change(self.events_path, remaining)

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

    def _cleanup_archives(self, archive_dir: Path) -> None:
        """Compress and delete old files in the archive directory."""
        now = datetime.now(timezone.utc)
        for f in archive_dir.iterdir():
            if not f.is_file():
                continue

            try:
                # Check creation/modification time
                file_mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                age = now - file_mtime

                # Delete files older than 30 days
                if age.days > 30:
                    f.unlink()
                    logger.info("Deleted old archive file: %s", f.name)
                    continue

                # Compress files older than 7 days if not already compressed
                if age.days > 7 and f.suffix != ".gz":
                    with f.open("rb") as f_in:
                        with gzip.open(str(f) + ".gz", "wb") as f_out:
                            f_out.writelines(f_in)
                    f.unlink()
                    logger.info("Compressed archive file: %s", f.name)
            except Exception as e:
                logger.warning("Error processing archive file %s: %s", f.name, e)

    def _prune_logs_directory(
        self,
        log_dir: Path,
        prefix: str,
        max_files: int,
        compress_after_days: int,
        delete_after_days: int,
    ) -> None:
        """Prunes log files in a directory, keeping newest, compressing older, and deleting oldest."""
        if not log_dir.is_dir():
            return

        now = datetime.now(timezone.utc)
        files_to_process: list[tuple[float, Path]] = []

        for f in log_dir.iterdir():
            if not f.is_file():
                continue
            # Handle both original and compressed files
            if f.name.startswith(prefix) and (f.suffix == ".log" or f.suffix == ".gz"):
                files_to_process.append((f.stat().st_mtime, f))

        # Sort by modification time, newest first
        files_to_process.sort(key=lambda x: x[0], reverse=True)

        # Separate files for count-based pruning and age-based processing
        files_to_prune_by_count = files_to_process[max_files:]
        files_for_age_processing = files_to_process[:max_files] # only process the ones we're keeping by count for age

        # Perform age-based processing on all files that are not immediately pruned by count
        for mtime, f in files_for_age_processing + files_to_prune_by_count:
            file_mtime = datetime.fromtimestamp(mtime, tz=timezone.utc)
            age_days = (now - file_mtime).days

            if age_days > delete_after_days:
                try:
                    f.unlink()
                    logger.info("Deleted old log file (age > %d days): %s", delete_after_days, f.name)
                except Exception as e:
                    logger.warning("Error deleting log file %s: %s", f.name, e)
            elif age_days > compress_after_days and f.suffix != ".gz":
                try:
                    with f.open("rb") as f_in:
                        with gzip.open(str(f) + ".gz", "wb") as f_out:
                            f_out.writelines(f_in)
                    f.unlink()
                    logger.info("Compressed old log file (age > %d days): %s", compress_after_days, f.name)
                except Exception as e:
                    logger.warning("Error compressing log file %s: %s", f.name, e)

        # Finally, delete any files that are still left and exceed max_files (if not already handled by age)
        # Re-list to get the current state after age-based processing
        current_files_for_prefix = []
        for f in log_dir.iterdir():
            if not f.is_file():
                continue
            if f.name.startswith(prefix) and (f.suffix == ".log" or f.suffix == ".gz"):
                current_files_for_prefix.append((f.stat().st_mtime, f))
        current_files_for_prefix.sort(key=lambda x: x[0], reverse=True)

        if len(current_files_for_prefix) > max_files:
            for mtime, f in current_files_for_prefix[max_files:]:
                try:
                    f.unlink()
                    logger.info("Pruning excess log file (beyond max_files): %s", f.name)
                except Exception as e:
                    logger.warning("Error pruning excess log file %s: %s", f.name, e)

    def compact_events(self, retention_limit: int = 500) -> Dict[str, Any]:
        """Archive events beyond retention limit to a rotated file.

        Keeps the newest *retention_limit* events in events.jsonl and writes
        older events to bus/archive/events.<timestamp>.jsonl.

        Returns dict with archived count, retained count, and the offset
        adjustment that callers must apply to agent cursors.
        """
        archive_dir = self.root / "archive"

        with self._file_lock(self._events_lock):
            if not self.events_path.exists():
                return {"archived": 0, "retained": 0, "offset_adjustment": 0}

            # Read raw lines (preserves original JSON exactly).
            with self.events_path.open("r", encoding="utf-8") as fh:
                lines = [line for line in fh if line.strip()]

            total = len(lines)
            if total <= retention_limit:
                return {"archived": 0, "retained": total, "offset_adjustment": 0}

            cut = total - retention_limit
            to_archive = lines[:cut]
            to_retain = lines[cut:]

            # Write archive file.
            archive_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive_path = archive_dir / f"events.{ts}.jsonl"
            with archive_path.open("w", encoding="utf-8") as fh:
                for raw in to_archive:
                    fh.write(raw if raw.endswith("\n") else raw + "\n")
                fh.flush()
                os.fsync(fh.fileno())

            # Atomic rewrite of events.jsonl with retained events only.
            tmp = self.events_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for raw in to_retain:
                    fh.write(raw if raw.endswith("\n") else raw + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(self.events_path)
            self._cleanup_archives(archive_dir)

            return {
                "archived": cut,
                "retained": len(to_retain),
                "offset_adjustment": cut,
                "archive_path": str(archive_path),
            }

    def write_command(self, task_id: str, command: Dict[str, Any]) -> Path:
        path = self.commands_dir / f"{task_id}.json"
        lock = self._lock_for(path)
        with self._file_lock(lock):
            self._atomic_write_json(path, command)
        return path

    def write_report(self, task_id: str, report: Dict[str, Any], mtime: Optional[float] = None) -> Path:
        path = self.reports_dir / f"{task_id}.json"
        lock = self._lock_for(path)
        with self._file_lock(lock):
            self._atomic_write_json(path, report)
            if mtime is not None:
                os.utime(path, (mtime, mtime)) # Set access and modification times
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
                try:
                    os.fsync(fh.fileno())
                except OSError as e:
                    logger.warning("audit fsync failed: %s", e)
            try:
                # Rotate audit log if it grows too large (>50MB)
                if self.audit_path.stat().st_size > 50 * 1024 * 1024: # 50 MB
                    archive_dir = self.root / "archive"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    archive_path = archive_dir / f"audit.{ts}.jsonl"
                    self.audit_path.rename(archive_path)
                    logger.info("audit.rotated size=%d archive=%s", archive_path.stat().st_size, archive_path.name)
                    # Compress immediately after rotation
                    with archive_path.open("rb") as f_in:
                        with gzip.open(str(archive_path) + ".gz", "wb") as f_out:
                            f_out.writelines(f_in)
                    archive_path.unlink() # Delete the uncompressed archive
                    logger.info("Compressed rotated audit file: %s", archive_path.name + ".gz")
                self._cleanup_archives(archive_dir)
            except Exception as e:
                logger.debug("audit rotation check failed: %s", e)
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
