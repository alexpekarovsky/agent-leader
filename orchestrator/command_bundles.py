"""Command bundles and startup templates for agent-leader orchestrator v0.3.

Provides:
- load_command_bundles(): Load slash-command bundle definitions from YAML config
- list_command_bundles(): List available bundles with metadata
- get_command_bundle(): Get a specific bundle by name
- load_startup_template(): Load and render a startup prompt template
- list_startup_templates(): List available startup templates
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_BUNDLES_PATH = _CONFIG_DIR / "command_bundles.yaml"
_TEMPLATES_DIR = _CONFIG_DIR / "startup_templates"

# Cache
_bundles_cache: Optional[Dict[str, Any]] = None


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file, falling back to basic parsing if PyYAML unavailable."""
    if yaml is not None:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    # Minimal fallback: return empty dict so callers degrade gracefully
    return {}


def load_command_bundles(*, force: bool = False) -> Dict[str, Any]:
    """Load command bundle definitions from config/command_bundles.yaml."""
    global _bundles_cache
    if _bundles_cache is not None and not force:
        return _bundles_cache
    if not _BUNDLES_PATH.exists():
        _bundles_cache = {}
        return _bundles_cache
    data = _load_yaml(_BUNDLES_PATH)
    _bundles_cache = data.get("bundles", {})
    return _bundles_cache


def list_command_bundles() -> List[Dict[str, Any]]:
    """Return a list of available command bundles with metadata."""
    bundles = load_command_bundles()
    result = []
    for name, bundle in sorted(bundles.items()):
        result.append({
            "name": name,
            "description": bundle.get("description", ""),
            "category": bundle.get("category", "general"),
            "step_count": len(bundle.get("steps", [])),
            "tools": [s["tool"] for s in bundle.get("steps", [])],
        })
    return result


def get_command_bundle(name: str) -> Optional[Dict[str, Any]]:
    """Get a specific command bundle by name, or None if not found."""
    bundles = load_command_bundles()
    bundle = bundles.get(name)
    if bundle is None:
        return None
    return {
        "name": name,
        "description": bundle.get("description", ""),
        "category": bundle.get("category", "general"),
        "steps": bundle.get("steps", []),
    }


def list_startup_templates() -> List[Dict[str, str]]:
    """List available startup templates."""
    if not _TEMPLATES_DIR.exists():
        return []
    result = []
    for p in sorted(_TEMPLATES_DIR.glob("*.txt")):
        # Read first line as description hint
        first_line = ""
        try:
            first_line = p.read_text().split("\n", 1)[0].strip()
        except Exception:
            pass
        result.append({
            "name": p.stem,
            "file": p.name,
            "first_line": first_line,
        })
    return result


def load_startup_template(
    name: str,
    variables: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Load a startup template by name and render variables.

    Variables use {{key}} placeholder syntax.
    Unresolved placeholders are left as-is.
    """
    path = _TEMPLATES_DIR / f"{name}.txt"
    if not path.exists():
        return None
    content = path.read_text()
    if variables:
        for key, value in variables.items():
            content = content.replace("{{" + key + "}}", str(value))
    return content
