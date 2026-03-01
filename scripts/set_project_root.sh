#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF' 1>&2
Usage:
  eval "$(./scripts/set_project_root.sh)"          # use current directory
  eval "$(./scripts/set_project_root.sh /path)"    # use explicit project root

Sets:
  ORCHESTRATOR_ROOT
  ORCHESTRATOR_EXPECTED_ROOT
  ORCHESTRATOR_POLICY (if config/policy.codex-manager.json exists)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "" ]]; then
  target="."
elif [[ $# -eq 1 ]]; then
  target="$1"
else
  usage
  exit 2
fi

if ! root_abs="$(cd "$target" && pwd -P)"; then
  echo "echo 'set_project_root: invalid path: $target' 1>&2" 
  exit 1
fi

policy_path="$root_abs/config/policy.codex-manager.json"

printf 'export ORCHESTRATOR_ROOT=%q\n' "$root_abs"
printf 'export ORCHESTRATOR_EXPECTED_ROOT=%q\n' "$root_abs"
if [[ -f "$policy_path" ]]; then
  printf 'export ORCHESTRATOR_POLICY=%q\n' "$policy_path"
fi
printf 'echo %q\n' "orchestrator project root set: $root_abs"

