#!/usr/bin/env python3
"""OS-native file watcher for event-driven worker wakeup.

Watches a signal file for modifications using the best available mechanism:
- macOS/BSD: kqueue (KQ_FILTER_VNODE on parent directory)
- Linux: inotify (via ctypes)
- Fallback: mtime polling at 200ms intervals

Usage:
    fswatcher.py <signal_file> <max_wait_seconds> [--baseline-mtime <ms>]

Exit codes:
    0 - signal file was modified (new work available)
    1 - timeout with no signal
    2 - usage error
"""
from __future__ import annotations

import os
import sys
import time


def _current_mtime_ms(path: str) -> int:
    """Return file mtime in milliseconds, or 0 if missing."""
    try:
        return int(os.path.getmtime(path) * 1000)
    except OSError:
        return 0


def watch_kqueue(path: str, timeout: float, baseline_mtime: int) -> int:
    """Watch using kqueue (macOS/BSD).

    Watches the signal file itself for content changes (KQ_NOTE_WRITE) and
    the parent directory for file creation (KQ_NOTE_WRITE on dir) in case
    the signal file doesn't exist yet.
    """
    import select

    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    kq = select.kqueue()
    fds_to_close: list[int] = []

    try:
        kevents: list[select.kevent] = []

        # Watch the file itself if it already exists (content changes)
        if os.path.exists(path):
            file_fd = os.open(path, os.O_RDONLY)
            fds_to_close.append(file_fd)
            kevents.append(
                select.kevent(
                    file_fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB,
                )
            )

        # Watch parent directory for file creation/rename
        dir_fd = os.open(parent, os.O_RDONLY)
        fds_to_close.append(dir_fd)
        kevents.append(
            select.kevent(
                dir_fd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                fflags=select.KQ_NOTE_WRITE,
            )
        )

        deadline = time.monotonic() + timeout
        # Check once immediately in case signal arrived before we started watching
        cur = _current_mtime_ms(path)
        if cur != baseline_mtime and cur != 0:
            return 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 1
            events = kq.control(kevents, len(kevents), min(remaining, 1.0))
            if events:
                cur = _current_mtime_ms(path)
                if cur != baseline_mtime and cur != 0:
                    return 0
            else:
                # Periodic mtime safety check even without events
                cur = _current_mtime_ms(path)
                if cur != baseline_mtime and cur != 0:
                    return 0
    finally:
        kq.close()
        for fd in fds_to_close:
            os.close(fd)


def watch_inotify(path: str, timeout: float, baseline_mtime: int) -> int:
    """Watch using inotify (Linux)."""
    import ctypes
    import ctypes.util
    import select as sel

    libc_name = ctypes.util.find_library("c")
    if not libc_name:
        raise OSError("libc not found")
    libc = ctypes.CDLL(libc_name, use_errno=True)

    IN_MODIFY = 0x00000002
    IN_CREATE = 0x00000100
    IN_MOVED_TO = 0x00000080
    IN_NONBLOCK = 0x00000800

    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    ifd = libc.inotify_init1(IN_NONBLOCK)
    if ifd < 0:
        raise OSError("inotify_init1 failed")

    wd = libc.inotify_add_watch(
        ifd, parent.encode("utf-8"), IN_MODIFY | IN_CREATE | IN_MOVED_TO
    )
    if wd < 0:
        os.close(ifd)
        raise OSError("inotify_add_watch failed")

    try:
        # Check once immediately
        cur = _current_mtime_ms(path)
        if cur != baseline_mtime and cur != 0:
            return 0
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 1
            ready, _, _ = sel.select([ifd], [], [], min(remaining, 1.0))
            if ready:
                try:
                    os.read(ifd, 4096)
                except OSError:
                    pass
                cur = _current_mtime_ms(path)
                if cur != baseline_mtime and cur != 0:
                    return 0
    finally:
        os.close(ifd)


def watch_poll(path: str, timeout: float, baseline_mtime: int) -> int:
    """Fallback polling watcher at 200ms intervals."""
    deadline = time.monotonic() + timeout
    # Check once immediately
    cur = _current_mtime_ms(path)
    if cur != baseline_mtime and cur != 0:
        return 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return 1
        time.sleep(min(0.2, remaining))
        cur = _current_mtime_ms(path)
        if cur != baseline_mtime and cur != 0:
            return 0


def detect_backend() -> str:
    """Detect best available watching backend."""
    try:
        import select

        if hasattr(select, "kqueue"):
            return "kqueue"
    except ImportError:
        pass

    if sys.platform.startswith("linux"):
        try:
            import ctypes
            import ctypes.util

            if ctypes.util.find_library("c"):
                return "inotify"
        except ImportError:
            pass

    return "poll"


def watch(path: str, timeout: float, baseline_mtime: int) -> int:
    """Watch signal file using best available backend."""
    backend = detect_backend()

    if backend == "kqueue":
        try:
            return watch_kqueue(path, timeout, baseline_mtime)
        except Exception:
            pass

    if backend == "inotify":
        try:
            return watch_inotify(path, timeout, baseline_mtime)
        except Exception:
            pass

    return watch_poll(path, timeout, baseline_mtime)


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: fswatcher.py <signal_file> <max_wait_seconds> [--baseline-mtime <ms>]",
            file=sys.stderr,
        )
        sys.exit(2)

    signal_file = sys.argv[1]
    try:
        max_wait = float(sys.argv[2])
    except ValueError:
        print(f"Invalid max_wait: {sys.argv[2]}", file=sys.stderr)
        sys.exit(2)

    baseline_mtime = 0
    if "--baseline-mtime" in sys.argv:
        idx = sys.argv.index("--baseline-mtime")
        if idx + 1 < len(sys.argv):
            try:
                baseline_mtime = int(sys.argv[idx + 1])
            except ValueError:
                baseline_mtime = 0

    # Print backend for diagnostics
    backend = detect_backend()
    print(f"fswatcher: backend={backend} file={signal_file} timeout={max_wait}s", file=sys.stderr)

    sys.exit(watch(signal_file, max_wait, baseline_mtime))


if __name__ == "__main__":
    main()
