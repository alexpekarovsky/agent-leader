#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY_PATH="${1:-$ROOT_DIR/config/policy.codex-manager.json}"

printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"orchestrator_bootstrap","arguments":{}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"orchestrator_status","arguments":{}}}' \
| ORCHESTRATOR_ROOT="$ROOT_DIR" ORCHESTRATOR_POLICY="$POLICY_PATH" python3 "$ROOT_DIR/orchestrator_mcp_server.py"
