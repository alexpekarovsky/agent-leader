#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SOURCE_ROOT="$ROOT_DIR"
PROJECT_ROOT="$ROOT_DIR"
POLICY_PATH=""

INSTALL_CLAUDE=false
INSTALL_GEMINI=false
INSTALL_CODEX=false
MODE="project" # project|global
CONFIRM_GLOBAL=false
ALLOW_EPHEMERAL=false
REPLACE_LEGACY=false
ROLLBACK_ID=""

SERVER_NAME="agent-leader-orchestrator"
APP_INSTALL_BASE_DEFAULT="$HOME/.local/share/agent-leader"
APP_INSTALL_BASE="${AGENT_LEADER_INSTALL_ROOT:-$APP_INSTALL_BASE_DEFAULT}"

usage() {
  cat <<USAGE
Usage: $0 [--claude] [--gemini] [--codex] [--all] [--mode project|global] [--confirm-global] [--server-root PATH] [--project-root PATH] [--policy PATH] [--allow-ephemeral] [--replace-legacy] [--rollback BACKUP_ID]

Examples:
  $0 --all
  $0 --all --project-root /path/to/your/repo
  $0 --all --server-root /path/to/agent-leader --project-root /path/to/your/repo
  $0 --all --mode global --confirm-global
  $0 --all --replace-legacy
  $0 --rollback BACKUP-20260215-123000
USAGE
}

canon_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

is_ephemeral_path() {
  local p="$1"
  case "$p" in
    /tmp|/tmp/*|/private/tmp|/private/tmp/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)
      INSTALL_CLAUDE=true
      shift
      ;;
    --gemini)
      INSTALL_GEMINI=true
      shift
      ;;
    --codex)
      INSTALL_CODEX=true
      shift
      ;;
    --all)
      INSTALL_CLAUDE=true
      INSTALL_GEMINI=true
      INSTALL_CODEX=true
      shift
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --scope)
      # Backward-compatible alias.
      if [[ "$2" == "user" ]]; then
        MODE="global"
      else
        MODE="project"
      fi
      shift 2
      ;;
    --confirm-global)
      CONFIRM_GLOBAL=true
      shift
      ;;
    --allow-ephemeral)
      ALLOW_EPHEMERAL=true
      shift
      ;;
    --replace-legacy)
      REPLACE_LEGACY=true
      shift
      ;;
    --rollback)
      ROLLBACK_ID="$2"
      shift 2
      ;;
    --root)
      SOURCE_ROOT="$2"
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --server-root)
      SOURCE_ROOT="$2"
      shift 2
      ;;
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --policy)
      POLICY_PATH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

SOURCE_ROOT="$(canon_path "$SOURCE_ROOT")"
PROJECT_ROOT="$(canon_path "$PROJECT_ROOT")"
APP_INSTALL_BASE="$(canon_path "$APP_INSTALL_BASE")"

if [[ -n "$ROLLBACK_ID" ]]; then
  BACKUP_ROOT="$PROJECT_ROOT/state/install_backups"
  MANIFEST="$BACKUP_ROOT/$ROLLBACK_ID/manifest.json"
  if [[ ! -f "$MANIFEST" ]]; then
    echo "Rollback manifest not found: $MANIFEST" >&2
    exit 1
  fi
  python3 - "$MANIFEST" <<'PY'
import json
import shutil
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
raw = json.loads(manifest.read_text(encoding="utf-8"))
for item in raw.get("files", []):
    target = Path(item["target"]).expanduser()
    backup = Path(item["backup"]).expanduser()
    existed = bool(item.get("existed"))
    target.parent.mkdir(parents=True, exist_ok=True)
    if existed:
      shutil.copy2(backup, target)
    else:
      if target.exists():
        target.unlink()
print("Rollback completed.")
PY
  exit 0
fi

if [[ "$INSTALL_CLAUDE" == false && "$INSTALL_GEMINI" == false && "$INSTALL_CODEX" == false ]]; then
  echo "No target selected. Use --claude, --gemini, --codex, or --all." >&2
  exit 1
fi

if [[ "$MODE" != "project" && "$MODE" != "global" ]]; then
  echo "Invalid --mode '$MODE'. Use project|global." >&2
  exit 1
fi
if [[ "$MODE" == "global" && "$CONFIRM_GLOBAL" != true ]]; then
  echo "Global mode requires explicit --confirm-global." >&2
  exit 1
fi

if is_ephemeral_path "$SOURCE_ROOT" && [[ "$ALLOW_EPHEMERAL" != true ]]; then
  echo "Refusing ephemeral --server-root: $SOURCE_ROOT" >&2
  echo "Use a stable path or pass --allow-ephemeral explicitly." >&2
  exit 1
fi

SOURCE_SERVER_PATH="$SOURCE_ROOT/orchestrator_mcp_server.py"
if [[ ! -f "$SOURCE_SERVER_PATH" ]]; then
  echo "Missing server file: $SOURCE_SERVER_PATH" >&2
  exit 1
fi

APP_VERSION="$(python3 - "$SOURCE_SERVER_PATH" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else '0.0.0')
PY
)"
TARGET_DIR="$APP_INSTALL_BASE/$APP_VERSION"
TARGET_DIR="$(canon_path "$TARGET_DIR")"
mkdir -p "$TARGET_DIR"

# Install stable app payload.
mkdir -p "$TARGET_DIR/orchestrator" "$TARGET_DIR/config"
cp "$SOURCE_ROOT/orchestrator_mcp_server.py" "$TARGET_DIR/orchestrator_mcp_server.py"
cp "$SOURCE_ROOT/orchestrator"/*.py "$TARGET_DIR/orchestrator/"
cp "$SOURCE_ROOT/config"/*.json "$TARGET_DIR/config/"

SERVER_PATH="$TARGET_DIR/orchestrator_mcp_server.py"
DEFAULT_POLICY_PATH="$TARGET_DIR/config/policy.codex-manager.json"

if [[ -z "$POLICY_PATH" ]]; then
  POLICY_PATH="$DEFAULT_POLICY_PATH"
else
  if [[ "$POLICY_PATH" != /* ]]; then
    if [[ -f "$SOURCE_ROOT/$POLICY_PATH" ]]; then
      POLICY_PATH="$SOURCE_ROOT/$POLICY_PATH"
    fi
  fi
  POLICY_PATH="$(canon_path "$POLICY_PATH")"
  # If policy came from source tree and has a copied counterpart, use stable target copy.
  if [[ "$POLICY_PATH" == "$SOURCE_ROOT/"* ]]; then
    rel="${POLICY_PATH#"$SOURCE_ROOT/"}"
    if [[ -f "$TARGET_DIR/$rel" ]]; then
      POLICY_PATH="$TARGET_DIR/$rel"
    fi
  fi
fi

if [[ ! -f "$POLICY_PATH" ]]; then
  echo "Missing policy file: $POLICY_PATH" >&2
  exit 1
fi

if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Missing project root: $PROJECT_ROOT" >&2
  exit 1
fi

ENV_ROOT="ORCHESTRATOR_ROOT=$PROJECT_ROOT"
ENV_EXPECTED_ROOT="ORCHESTRATOR_EXPECTED_ROOT=$PROJECT_ROOT"
ENV_POLICY="ORCHESTRATOR_POLICY=$POLICY_PATH"

INSTALL_AUDIT_PATH="$PROJECT_ROOT/state/install_audit.jsonl"
BACKUP_ROOT="$PROJECT_ROOT/state/install_backups"
mkdir -p "$(dirname "$INSTALL_AUDIT_PATH")" "$BACKUP_ROOT"

BACKUP_ID="BACKUP-$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$BACKUP_ID"
mkdir -p "$BACKUP_DIR"

backup_configs() {
  local manifest="$BACKUP_DIR/manifest.json"
  python3 - "$manifest" "$PROJECT_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
project_root = Path(sys.argv[2]).expanduser().resolve()
targets = [
    Path.home()/'.claude.json',
    project_root/'.mcp.json',
    Path.home()/'.codex'/'config.toml',
    Path.home()/'.gemini'/'settings.json',
    project_root/'.gemini'/'settings.json',
]
files = []
for target in targets:
    target = target.expanduser().resolve()
    backup = manifest.parent / (target.as_posix().replace('/', '__').replace(':','_') + '.bak')
    exists = target.exists()
    if exists:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(target.read_bytes())
    files.append({"target": str(target), "backup": str(backup), "existed": exists})
manifest.write_text(json.dumps({"backup_id": manifest.parent.name, "files": files}, indent=2), encoding='utf-8')
PY
}

restore_backup() {
  local manifest="$BACKUP_DIR/manifest.json"
  if [[ ! -f "$manifest" ]]; then
    return
  fi
  python3 - "$manifest" <<'PY'
import json
from pathlib import Path
import shutil
import sys

manifest = Path(sys.argv[1])
raw = json.loads(manifest.read_text(encoding='utf-8'))
for item in raw.get('files', []):
    target = Path(item['target']).expanduser()
    backup = Path(item['backup']).expanduser()
    existed = bool(item.get('existed'))
    target.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        if backup.exists():
            shutil.copy2(backup, target)
    else:
        if target.exists():
            target.unlink()
PY
}

log_install_audit() {
  local target_cli="$1"
  local status="$2"
  local message="${3:-}"
  python3 - "$INSTALL_AUDIT_PATH" "$target_cli" "$status" "$MODE" "$SERVER_NAME" "$SERVER_PATH" "$POLICY_PATH" "$PROJECT_ROOT" "$BACKUP_ID" "$message" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

audit_path = Path(sys.argv[1])
entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "category": "install",
    "target_cli": sys.argv[2],
    "status": sys.argv[3],
    "mode": sys.argv[4],
    "server_name": sys.argv[5],
    "server_path": sys.argv[6],
    "policy_path": sys.argv[7],
    "project_root": sys.argv[8],
    "backup_id": sys.argv[9],
    "message": sys.argv[10],
}
with audit_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry) + "\n")
PY
}

backup_configs

auto_rollback_on_err() {
  echo "Install failed. Restoring backups ($BACKUP_ID)..." >&2
  restore_backup
  log_install_audit "installer" "rollback" "auto-rollback executed after failure"
}
trap auto_rollback_on_err ERR

CLAUDE_SCOPE="project"
if [[ "$MODE" == "global" ]]; then
  CLAUDE_SCOPE="user"
fi

if [[ "$INSTALL_CLAUDE" == true ]]; then
  echo "Installing for Claude Code ($MODE)..."
  if [[ "$REPLACE_LEGACY" == true ]]; then
    claude mcp remove orchestrator >/dev/null 2>&1 || true
  fi
  claude mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  claude mcp add --scope "$CLAUDE_SCOPE" "$SERVER_NAME" env "$ENV_ROOT" "$ENV_EXPECTED_ROOT" "$ENV_POLICY" python3 "$SERVER_PATH"
  log_install_audit "claude" "ok" "installed"
fi

if [[ "$INSTALL_GEMINI" == true ]]; then
  echo "Installing for Gemini CLI ($MODE)..."
  if [[ "$REPLACE_LEGACY" == true ]]; then
    gemini mcp remove orchestrator >/dev/null 2>&1 || true
  fi
  gemini mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  gemini mcp add "$SERVER_NAME" env "$ENV_ROOT" "$ENV_EXPECTED_ROOT" "$ENV_POLICY" python3 "$SERVER_PATH"
  log_install_audit "gemini" "ok" "installed"
fi

if [[ "$INSTALL_CODEX" == true ]]; then
  echo "Installing for Codex CLI ($MODE)..."
  if [[ "$REPLACE_LEGACY" == true ]]; then
    codex mcp remove orchestrator >/dev/null 2>&1 || true
  fi
  codex mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  codex mcp add "$SERVER_NAME" --env "$ENV_ROOT" --env "$ENV_EXPECTED_ROOT" --env "$ENV_POLICY" -- python3 "$SERVER_PATH"
  log_install_audit "codex" "ok" "installed"
fi

trap - ERR

echo "Installed $SERVER_NAME"
echo "Mode: $MODE"
echo "Target: $TARGET_DIR"
echo "Project root: $PROJECT_ROOT"
echo "Backup ID: $BACKUP_ID"
echo "Done."
