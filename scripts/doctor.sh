#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROJECT_ROOT="$ROOT_DIR"
CHECK_CLAUDE=false
CHECK_GEMINI=false
CHECK_CODEX=false
SERVER_NAME="agent-leader-orchestrator"

usage() {
  cat <<USAGE
Usage: $0 [--claude] [--gemini] [--codex] [--all] [--project-root PATH]

Verifies real MCP registration and server command health.
USAGE
}

canon_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude)
      CHECK_CLAUDE=true
      shift
      ;;
    --gemini)
      CHECK_GEMINI=true
      shift
      ;;
    --codex)
      CHECK_CODEX=true
      shift
      ;;
    --all)
      CHECK_CLAUDE=true
      CHECK_GEMINI=true
      CHECK_CODEX=true
      shift
      ;;
    --project-root)
      PROJECT_ROOT="$2"
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

if [[ "$CHECK_CLAUDE" == false && "$CHECK_GEMINI" == false && "$CHECK_CODEX" == false ]]; then
  CHECK_CLAUDE=true
  CHECK_GEMINI=true
  CHECK_CODEX=true
fi

PROJECT_ROOT="$(canon_path "$PROJECT_ROOT")"

extract_server_path() {
  python3 - <<'PY'
import re, sys
text = sys.stdin.read()
m = re.search(r'(/[^\s]*orchestrator_mcp_server\.py)', text)
print(m.group(1) if m else '')
PY
}

check_server_binary() {
  local server_path="$1"
  if [[ -z "$server_path" ]]; then
    echo "no server path in MCP output" >&2
    return 1
  fi
  if [[ ! -f "$server_path" ]]; then
    echo "registered server path missing: $server_path" >&2
    return 1
  fi

  local server_dir policy
  server_dir="$(cd "$(dirname "$server_path")" && pwd -P)"
  policy="$server_dir/config/policy.codex-manager.json"
  if [[ ! -f "$policy" ]]; then
    policy="$PROJECT_ROOT/config/policy.codex-manager.json"
  fi
  if [[ ! -f "$policy" ]]; then
    echo "policy file not found for health check" >&2
    return 1
  fi

  local out
  out=$(printf '%s\n' \
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"orchestrator_status","arguments":{}}}' \
    | ORCHESTRATOR_ROOT="$PROJECT_ROOT" ORCHESTRATOR_EXPECTED_ROOT="$PROJECT_ROOT" ORCHESTRATOR_POLICY="$policy" python3 "$server_path")

  if ! printf '%s' "$out" | rg -q 'agent-leader-orchestrator'; then
    echo "server responded but health output missing server marker" >&2
    return 1
  fi
  return 0
}

fail=0

if [[ "$CHECK_CODEX" == true ]]; then
  echo "[doctor] codex"
  if ! out=$(codex mcp get "$SERVER_NAME" 2>/dev/null); then
    echo "codex: MCP entry missing ($SERVER_NAME)" >&2
    fail=1
  else
    path=$(printf '%s' "$out" | extract_server_path)
    if ! check_server_binary "$path"; then
      echo "codex: command path/health check failed" >&2
      fail=1
    fi
  fi
fi

if [[ "$CHECK_CLAUDE" == true ]]; then
  echo "[doctor] claude"
  if ! out=$(claude mcp get "$SERVER_NAME" 2>/dev/null); then
    echo "claude: MCP entry missing ($SERVER_NAME)" >&2
    fail=1
  else
    path=$(printf '%s' "$out" | extract_server_path)
    if ! check_server_binary "$path"; then
      echo "claude: command path/health check failed" >&2
      fail=1
    fi
  fi
fi

if [[ "$CHECK_GEMINI" == true ]]; then
  echo "[doctor] gemini"
  if ! out=$(gemini mcp list 2>/dev/null); then
    echo "gemini: unable to query MCP list (auth/session issue)" >&2
    fail=1
  else
    if ! printf '%s' "$out" | rg -q "$SERVER_NAME"; then
      echo "gemini: MCP entry missing ($SERVER_NAME)" >&2
      fail=1
    else
      path=$(printf '%s' "$out" | extract_server_path)
      if ! check_server_binary "$path"; then
        echo "gemini: command path/health check failed" >&2
        fail=1
      fi
    fi
  fi
fi

if [[ $fail -ne 0 ]]; then
  echo "doctor: failed" >&2
  exit 1
fi

echo "doctor: ok"
