"""Unified budget module — single JSON format with file locking.

Replaces three incompatible budget systems:
  - shell .count files  (common.sh consume_daily_budget)
  - persistent_worker .call_count.json files
  - MCP in-memory counter

File format per key: {"date": "YYYYMMDD", "count": <int>, "last_updated": <iso-ts>}
One file per (process_key, date) pair, stored as:
  <budget_dir>/.budget-<safe_key>-<YYYYMMDD>.json

All reads/writes use fcntl advisory locking to prevent races.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


def _safe_key(process_key: str) -> str:
    """Sanitise process_key for use in filenames."""
    return "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in process_key)


def _budget_path(process_key: str, budget_dir: str) -> Path:
    """Return the budget file path for today."""
    day = time.strftime("%Y%m%d")
    return Path(budget_dir) / f".budget-{_safe_key(process_key)}-{day}.json"


def _read_state(path: Path) -> dict:
    """Read budget state from *path*. Returns default dict if missing/corrupt."""
    today = time.strftime("%Y%m%d")
    default = {"date": today, "count": 0, "last_updated": ""}
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return default
        # Reset if date rolled over.
        if raw.get("date") != today:
            return default
        return raw
    except (json.JSONDecodeError, OSError):
        return default


def _write_state(path: Path, state: dict) -> None:
    """Atomically write budget state with an ISO timestamp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def consume_call(process_key: str, budget_limit: int, budget_dir: str) -> bool:
    """Consume one call from the daily budget for *process_key*.

    Returns True if the call is within budget, False if exhausted.
    A *budget_limit* of 0 means unlimited.
    """
    if budget_limit <= 0:
        return True  # 0 = unlimited

    budget_path = _budget_path(process_key, budget_dir)
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = budget_path.with_suffix(".lock")

    lock_fh: Optional[object] = None
    try:
        lock_fh = open(lock_path, "a+")
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)

        state = _read_state(budget_path)
        if state["count"] >= budget_limit:
            return False
        state["count"] += 1
        _write_state(budget_path, state)
        return True
    finally:
        if lock_fh is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            lock_fh.close()


def check_remaining(process_key: str, budget_limit: int, budget_dir: str) -> int:
    """Return remaining calls for *process_key* today.

    A *budget_limit* of 0 means unlimited (returns ``budget_limit``).
    """
    if budget_limit <= 0:
        return budget_limit  # 0 = unlimited sentinel

    budget_path = _budget_path(process_key, budget_dir)
    state = _read_state(budget_path)
    return max(0, budget_limit - state["count"])
