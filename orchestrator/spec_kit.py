"""Spec-kit: generate structured spec files from task descriptions.

Inspired by GitHub spec-kit (MIT). When a task is created, generates a
structured spec file that workers can reference for implementation guidance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("orchestrator.spec_kit")

SPECS_DIR_NAME = "specs"


def _specs_dir(bus_root: Path) -> Path:
    """Return the specs directory under the bus root, creating it if needed."""
    d = bus_root / SPECS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_spec(task: Dict[str, Any], bus_root: Path) -> Path:
    """Generate a structured spec file from a task dict.

    Returns the path to the written spec file.
    """
    task_id = task["id"]
    spec = {
        "task_id": task_id,
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "workstream": task.get("workstream", ""),
        "owner": task.get("owner", ""),
        "status": task.get("status", "assigned"),
        "acceptance_criteria": task.get("acceptance_criteria", []),
        "constraints": {
            "risk": task.get("delivery_profile", {}).get("risk", "medium"),
            "test_plan": task.get("delivery_profile", {}).get("test_plan", "targeted"),
            "doc_impact": task.get("delivery_profile", {}).get("doc_impact", "none"),
        },
        "references": {
            "parent_task_id": task.get("parent_task_id"),
            "project_name": task.get("project_name", ""),
            "project_root": task.get("project_root", ""),
            "team_id": task.get("team_id"),
            "tags": task.get("tags", []),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    spec_path = _specs_dir(bus_root) / f"{task_id}.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    logger.info("spec.generated task_id=%s path=%s", task_id, spec_path)
    return spec_path


def read_spec(task_id: str, bus_root: Path) -> Optional[Dict[str, Any]]:
    """Read a spec file for a given task ID. Returns None if not found."""
    spec_path = _specs_dir(bus_root) / f"{task_id}.json"
    if not spec_path.exists():
        return None
    return json.loads(spec_path.read_text(encoding="utf-8"))
