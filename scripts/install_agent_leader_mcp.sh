#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_ROOT="$ROOT_DIR"
PROJECT_ROOT="$ROOT_DIR"
SERVER_PATH=""
POLICY_PATH_DEFAULT=""

INSTALL_CLAUDE=false
INSTALL_GEMINI=false
INSTALL_CODEX=false
SCOPE="project"
POLICY_PATH=""

usage() {
  cat <<USAGE
Usage: $0 [--claude] [--gemini] [--codex] [--all] [--scope project|user] [--server-root PATH] [--project-root PATH] [--policy PATH]

Examples:
  $0 --all
  $0 --all --project-root /path/to/your/repo
  $0 --all --server-root /path/to/agent-leader --project-root /path/to/your/repo
  $0 --claude --codex --scope project
  $0 --gemini --policy /path/to/agent-leader/config/policy.shared-governance.json
USAGE
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
    --scope)
      SCOPE="$2"
      shift 2
      ;;
    --root)
      SERVER_ROOT="$2"
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --server-root)
      SERVER_ROOT="$2"
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

if [[ "$INSTALL_CLAUDE" == false && "$INSTALL_GEMINI" == false && "$INSTALL_CODEX" == false ]]; then
  echo "No target selected. Use --claude, --gemini, --codex, or --all." >&2
  exit 1
fi

SERVER_PATH="$SERVER_ROOT/orchestrator_mcp_server.py"
POLICY_PATH_DEFAULT="$SERVER_ROOT/config/policy.codex-manager.json"
if [[ -z "$POLICY_PATH" ]]; then
  POLICY_PATH="$POLICY_PATH_DEFAULT"
fi

if [[ ! -f "$SERVER_PATH" ]]; then
  echo "Missing server file: $SERVER_PATH" >&2
  exit 1
fi

if [[ ! -f "$POLICY_PATH" ]]; then
  echo "Missing policy file: $POLICY_PATH" >&2
  exit 1
fi

ENV_ROOT="ORCHESTRATOR_ROOT=$PROJECT_ROOT"
ENV_EXPECTED_ROOT="ORCHESTRATOR_EXPECTED_ROOT=$PROJECT_ROOT"
ENV_POLICY="ORCHESTRATOR_POLICY=$POLICY_PATH"

SERVER_NAME="agent-leader-orchestrator"

if [[ "$INSTALL_CLAUDE" == true ]]; then
  echo "Installing for Claude Code ($SCOPE scope)..."
  claude mcp remove orchestrator >/dev/null 2>&1 || true
  claude mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  claude mcp add --scope "$SCOPE" "$SERVER_NAME" env "$ENV_ROOT" "$ENV_EXPECTED_ROOT" "$ENV_POLICY" python3 "$SERVER_PATH"
  claude mcp list | sed -n '/agent-leader-orchestrator/p'
fi

if [[ "$INSTALL_GEMINI" == true ]]; then
  echo "Installing for Gemini CLI ($SCOPE scope)..."
  gemini mcp remove orchestrator >/dev/null 2>&1 || true
  gemini mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  gemini mcp add "$SERVER_NAME" env "$ENV_ROOT" "$ENV_EXPECTED_ROOT" "$ENV_POLICY" python3 "$SERVER_PATH"
  gemini mcp list | sed -n '/agent-leader-orchestrator/p'
fi

if [[ "$INSTALL_CODEX" == true ]]; then
  echo "Installing for Codex CLI..."
  codex mcp remove orchestrator >/dev/null 2>&1 || true
  codex mcp remove "$SERVER_NAME" >/dev/null 2>&1 || true
  codex mcp add "$SERVER_NAME" --env "$ENV_ROOT" --env "$ENV_EXPECTED_ROOT" --env "$ENV_POLICY" -- python3 "$SERVER_PATH"
  codex mcp list | sed -n '/agent-leader-orchestrator/p'
fi

echo "Done."
