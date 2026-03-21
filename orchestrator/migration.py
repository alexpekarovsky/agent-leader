"""Versioned state schema migration for orchestrator state files.

Each state record gets a ``schema_version`` field.  A separate
``state/schema_meta.json`` tracks the directory-level version.
``migrate_state()`` upgrades legacy (v0 / no-version) schemas to current.

Supported state files: tasks.json, agents.json, events.jsonl.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Current schema version stamped into state records and schema_meta.json.
CURRENT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Per-file migration helpers
# ---------------------------------------------------------------------------


def _migrate_tasks_v0_to_v1(tasks: List) -> bool:
    """Stamp schema_version on each task record and backfill v1 fields.

    The top-level list format is preserved (no wrapper) so existing callers
    of ``_read_json(tasks_path)`` continue to receive a plain list.

    Returns True if any record was modified.
    """
    changed = False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("schema_version", 0) < 1:
            task["schema_version"] = 1
            task.setdefault("team_id", None)
            task.setdefault("parent_task_id", None)
            task.setdefault("tags", [])
            task.setdefault("delivery_profile", {
                "risk": "low",
                "test_plan": "smoke",
                "doc_impact": "none",
            })
            changed = True
    return changed


def _migrate_agents_v0_to_v1(agents: Dict) -> bool:
    """Stamp schema_version on each agent entry.

    The top-level dict-keyed-by-name format is preserved so existing callers
    continue to work unchanged.

    Returns True if any record was modified.
    """
    changed = False
    for _name, entry in agents.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("schema_version", 0) < 1:
            entry["schema_version"] = 1
            changed = True
    return changed


def _migrate_events_v0_to_v1(events_path: Path) -> int:
    """Stamp schema_version on each event line in events.jsonl.

    Returns the number of lines rewritten.  File is left untouched when
    all lines already carry a version field.
    """
    if not events_path.exists():
        return 0

    lines = events_path.read_text(encoding="utf-8").splitlines()
    rewritten = 0
    new_lines: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        if isinstance(obj, dict) and "schema_version" not in obj:
            obj["schema_version"] = CURRENT_SCHEMA_VERSION
            new_lines.append(json.dumps(obj, separators=(",", ":")))
            rewritten += 1
        else:
            new_lines.append(line)
    if rewritten > 0:
        tmp = events_path.with_suffix(events_path.suffix + ".mig.tmp")
        tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        tmp.replace(events_path)
    return rewritten


# ---------------------------------------------------------------------------
# Schema metadata
# ---------------------------------------------------------------------------

def _read_schema_meta(state_dir: Path) -> Dict[str, Any]:
    """Read state/schema_meta.json or return default v0 metadata."""
    meta_path = state_dir / "schema_meta.json"
    if meta_path.exists():
        try:
            with meta_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return {"schema_version": 0}


def _write_schema_meta(state_dir: Path, meta: Dict[str, Any]) -> None:
    """Atomically write state/schema_meta.json."""
    meta_path = state_dir / "schema_meta.json"
    tmp = meta_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(meta_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_schema_version(state_dir: Path) -> int:
    """Return the current schema_version of the state directory, or 0 for legacy."""
    return int(_read_schema_meta(state_dir).get("schema_version", 0))


def migrate_state(
    state_dir: Path,
    bus_dir: Path,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Migrate all orchestrator state files from legacy (v0) to current schema.

    Parameters
    ----------
    state_dir : Path
        The ``state/`` directory containing tasks.json, agents.json, etc.
    bus_dir : Path
        The ``bus/`` directory containing events.jsonl.
    dry_run : bool
        If True, report what *would* change without writing anything.

    Returns
    -------
    dict
        Migration report with migrated/skipped/errors lists.
    """
    report: Dict[str, Any] = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "migrated": [],
        "skipped": [],
        "errors": [],
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    current_version = detect_schema_version(state_dir)
    if current_version >= CURRENT_SCHEMA_VERSION:
        report["skipped"] = ["tasks.json", "agents.json", "events.jsonl"]
        return report

    # --- tasks.json ---
    _migrate_list_file(
        path=state_dir / "tasks.json",
        name="tasks.json",
        migrator=_migrate_tasks_v0_to_v1,
        report=report,
        dry_run=dry_run,
    )

    # --- agents.json ---
    _migrate_dict_file(
        path=state_dir / "agents.json",
        name="agents.json",
        migrator=_migrate_agents_v0_to_v1,
        report=report,
        dry_run=dry_run,
    )

    # --- events.jsonl ---
    _migrate_events_file(
        events_path=bus_dir / "events.jsonl",
        report=report,
        dry_run=dry_run,
    )

    # Stamp schema_meta.json
    if not dry_run and not report["errors"]:
        _write_schema_meta(state_dir, {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "files": report["migrated"] + report["skipped"],
        })

    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON atomically (tmp + rename + fsync)."""
    tmp = path.with_suffix(path.suffix + ".mig.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def _migrate_list_file(
    *,
    path: Path,
    name: str,
    migrator,
    report: Dict[str, Any],
    dry_run: bool,
) -> None:
    """Migrate a JSON file that is a top-level list (e.g. tasks.json)."""
    try:
        if not path.exists():
            report["skipped"].append(name)
            return
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            report["skipped"].append(name)
            return
        changed = migrator(data)
        if not changed:
            report["skipped"].append(name)
            return
        if not dry_run:
            _atomic_write_json(path, data)
        report["migrated"].append(name)
    except Exception as exc:
        report["errors"].append({"file": name, "error": str(exc)})


def _migrate_dict_file(
    *,
    path: Path,
    name: str,
    migrator,
    report: Dict[str, Any],
    dry_run: bool,
) -> None:
    """Migrate a JSON file that is a top-level dict (e.g. agents.json)."""
    try:
        if not path.exists():
            report["skipped"].append(name)
            return
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            report["skipped"].append(name)
            return
        changed = migrator(data)
        if not changed:
            report["skipped"].append(name)
            return
        if not dry_run:
            _atomic_write_json(path, data)
        report["migrated"].append(name)
    except Exception as exc:
        report["errors"].append({"file": name, "error": str(exc)})


def _migrate_events_file(
    *,
    events_path: Path,
    report: Dict[str, Any],
    dry_run: bool,
) -> None:
    """Migrate events.jsonl — stamp schema_version on each event line."""
    try:
        if not events_path.exists():
            report["skipped"].append("events.jsonl")
            return
        if dry_run:
            lines = events_path.read_text(encoding="utf-8").splitlines()
            needs = any(
                isinstance((obj := _safe_json(l)), dict)
                and "schema_version" not in obj
                for l in lines
                if l.strip()
            )
            (report["migrated"] if needs else report["skipped"]).append("events.jsonl")
        else:
            count = _migrate_events_v0_to_v1(events_path)
            (report["migrated"] if count > 0 else report["skipped"]).append("events.jsonl")
    except Exception as exc:
        report["errors"].append({"file": "events.jsonl", "error": str(exc)})


def _safe_json(line: str) -> Any:
    """Parse JSON, returning None on failure."""
    try:
        return json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None
