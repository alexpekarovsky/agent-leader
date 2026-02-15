from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class Policy:
    name: str
    roles: Dict[str, str]
    routing: Dict[str, str]
    decisions: Dict[str, Any]
    triggers: Dict[str, Any]

    @staticmethod
    def load(path: Path) -> "Policy":
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        return Policy(
            name=raw.get("name", path.stem),
            roles=raw.get("roles", {}),
            routing=raw.get("routing", {}),
            decisions=raw.get("decisions", {}),
            triggers=raw.get("triggers", {}),
        )

    def manager(self) -> str:
        return self.roles.get("manager", "codex")

    def task_owner_for(self, workstream: str) -> str:
        return self.routing.get(workstream, self.routing.get("default", self.manager()))

    def architecture_mode(self) -> str:
        return str(self.decisions.get("architecture", {}).get("mode", "consensus"))

    def voters(self) -> List[str]:
        members = self.decisions.get("architecture", {}).get("members", [])
        if members:
            return members

        # Default equal-rights trio.
        return ["codex", "claude_code", "gemini"]
