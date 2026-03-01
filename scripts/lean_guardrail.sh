#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
CONFIG_PATH="${LEAN_MODE_CONFIG:-$REPO_ROOT/config/lean-mode.json}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[lean-guardrail] missing config: $CONFIG_PATH" >&2
  exit 2
fi

read_cfg() {
  local key="$1"
  python3 - "$CONFIG_PATH" "$key" <<'PY'
import json, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, 'r', encoding='utf-8') as f:
    cfg = json.load(f)
cur = cfg
for part in key.split('.'):
    cur = cur[part]
print(cur)
PY
}

ENABLED="$(read_cfg enabled)"
if [[ "$ENABLED" != "True" && "$ENABLED" != "true" ]]; then
  echo "[lean-guardrail] disabled"
  exit 0
fi

MAX_NEW_DOCS="$(read_cfg guardrails.max_new_docs)"
MAX_NEW_TEST_FILES="$(read_cfg guardrails.max_new_test_files)"
MAX_RATIO="$(read_cfg guardrails.max_test_to_code_loc_ratio)"
APPROVAL_LABELS="${LEAN_APPROVAL_LABELS:-}"

has_label() {
  local needle="$1"
  local hay="${APPROVAL_LABELS},"
  [[ "$hay" == *"$needle,"* ]]
}

cd "$REPO_ROOT"

NEW_FILES="$(git status --porcelain | awk '/^\?\?/ {print $2}')"
ADDED_FILES="$(git diff --name-status --cached | awk '$1=="A" {print $2}')"
ADDED_WT_FILES="$(git diff --name-status | awk '$1=="A" {print $2}')"
uniq_added="$(printf '%s\n%s\n%s\n' "$NEW_FILES" "$ADDED_FILES" "$ADDED_WT_FILES" | awk 'NF' | sort -u)"

canonical_docs=(
  "README.md"
  "CONTRIBUTING.md"
  "ROADMAP.md"
  "RELEASE_NOTES.md"
  "docs/operator-runbook.md"
)

is_canonical_doc() {
  local f="$1"
  for d in "${canonical_docs[@]}"; do
    [[ "$f" == "$d" ]] && return 0
  done
  return 1
}

new_docs=0
new_test_files=0

while IFS= read -r f; do
  [[ -z "$f" ]] && continue
  if [[ "$f" == *.md ]]; then
    if ! is_canonical_doc "$f"; then
      new_docs=$((new_docs + 1))
    fi
  fi
  if [[ "$f" == tests/*.py ]]; then
    new_test_files=$((new_test_files + 1))
  fi
done <<< "$uniq_added"

# LOC budget from working tree diff against HEAD.
# numstat columns: added deleted path
numstat="$(git diff --numstat HEAD -- '*.py' '*.sh' '*.ts' '*.tsx' '*.js' '*.jsx' || true)"

test_added=0
code_added=0
while read -r added _deleted path; do
  [[ -z "${path:-}" ]] && continue
  [[ "$added" == "-" ]] && continue
  if [[ "$path" == tests/* ]]; then
    test_added=$((test_added + added))
  else
    code_added=$((code_added + added))
  fi
done <<< "$numstat"

ratio="inf"
if (( code_added > 0 )); then
  ratio=$(python3 - <<PY
c=$code_added
t=$test_added
print(t/c)
PY
)
fi

echo "[lean-guardrail] new_docs=$new_docs (max=$MAX_NEW_DOCS)"
echo "[lean-guardrail] new_test_files=$new_test_files (max=$MAX_NEW_TEST_FILES)"
echo "[lean-guardrail] test_added=$test_added code_added=$code_added ratio=$ratio (max=$MAX_RATIO)"

fail=0
if (( new_docs > MAX_NEW_DOCS )); then
  if has_label "docs-approved"; then
    echo "[lean-guardrail] WARN: docs budget exceeded but docs-approved label is set"
  else
    echo "[lean-guardrail] FAIL: new docs exceed budget" >&2
    fail=1
  fi
fi
if (( new_test_files > MAX_NEW_TEST_FILES )); then
  if has_label "qa-approved"; then
    echo "[lean-guardrail] WARN: test-file budget exceeded but qa-approved label is set"
  else
    echo "[lean-guardrail] FAIL: new test files exceed budget" >&2
    fail=1
  fi
fi
if (( code_added == 0 && test_added > 0 )); then
  echo "[lean-guardrail] FAIL: test-only growth detected without code changes" >&2
  fail=1
elif (( code_added > 0 )); then
  python3 - "$ratio" "$MAX_RATIO" <<'PY'
import sys
ratio=float(sys.argv[1])
max_ratio=float(sys.argv[2])
if ratio > max_ratio:
    print("[lean-guardrail] FAIL: test/code LOC ratio exceeded", file=sys.stderr)
    raise SystemExit(1)
PY
  if [[ $? -ne 0 ]]; then
    fail=1
  fi
fi

if (( fail != 0 )); then
  exit 1
fi

echo "[lean-guardrail] PASS"
