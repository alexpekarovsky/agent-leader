#!/usr/bin/env bash
set -euo pipefail

# doc_guardrail.sh — enforce max-5 canonical docs policy
# See docs/DOC_POLICY.md for full policy details.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

# ── Canonical doc set (update when promoting/demoting) ──────────────────────
CANONICAL_DOCS=(
  "README.md"
  "CONTRIBUTING.md"
  "ROADMAP.md"
  "RELEASE_NOTES.md"
  "docs/operator-runbook.md"
)
MAX_CANONICAL=5

# ── Helpers ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YEL='\033[0;33m'
GRN='\033[0;32m'
RST='\033[0m'

now_epoch=$(date +%s)

file_age_days() {
  local f="$1"
  if [[ ! -f "$f" ]]; then echo "?"; return; fi
  local mtime
  if stat --version >/dev/null 2>&1; then
    mtime=$(stat -c %Y "$f")          # GNU/Linux
  else
    mtime=$(stat -f %m "$f")          # macOS
  fi
  echo $(( (now_epoch - mtime) / 86400 ))
}

age_label() {
  local days="$1"
  if [[ "$days" == "?" ]]; then echo "unknown"; return; fi
  if (( days <= 14 )); then   echo "active";
  elif (( days <= 30 )); then echo "review";
  else                        echo "stale";
  fi
}

# ── Check canonical set ────────────────────────────────────────────────────
echo "=== Canonical docs (max ${MAX_CANONICAL}) ==="
missing=0
for doc in "${CANONICAL_DOCS[@]}"; do
  full="$REPO_ROOT/$doc"
  if [[ -f "$full" ]]; then
    printf "  ${GRN}✓${RST} %s\n" "$doc"
  else
    printf "  ${RED}✗${RST} %s (MISSING)\n" "$doc"
    missing=$((missing + 1))
  fi
done

count=${#CANONICAL_DOCS[@]}
echo ""
printf "  Canonical count: %d / %d\n" "$count" "$MAX_CANONICAL"

if (( count > MAX_CANONICAL )); then
  printf "  ${RED}FAIL${RST}: canonical count exceeds max (%d > %d)\n" "$count" "$MAX_CANONICAL"
  exit_code=1
else
  printf "  ${GRN}OK${RST}\n"
  exit_code=0
fi

# ── Transient docs inventory ───────────────────────────────────────────────
echo ""
echo "=== Transient docs ==="

# Build canonical + excluded list for lookup (portable, no associative arrays)
SKIP_DOCS=("${CANONICAL_DOCS[@]}" "docs/DOC_POLICY.md")

is_skipped() {
  local rel="$1"
  for s in "${SKIP_DOCS[@]}"; do
    [[ "$rel" == "$s" ]] && return 0
  done
  return 1
}

transient_count=0
stale_count=0

while IFS= read -r -d '' mdfile; do
  rel="${mdfile#"$REPO_ROOT/"}"
  is_skipped "$rel" && continue

  days=$(file_age_days "$mdfile")
  label=$(age_label "$days")
  transient_count=$((transient_count + 1))

  case "$label" in
    active)  color="$GRN" ;;
    review)  color="$YEL" ;;
    stale)   color="$RED"; stale_count=$((stale_count + 1)) ;;
    *)       color="$RST" ;;
  esac

  printf "  ${color}%-8s${RST} (%3s days)  %s\n" "[$label]" "$days" "$rel"
done < <(find "$REPO_ROOT" -maxdepth 2 -name '*.md' \
           ! -path '*/.git/*' ! -path '*/.venv/*' \
           ! -path '*/node_modules/*' ! -path '*/_archive/*' \
           -print0 | sort -z)

echo ""
printf "  Transient: %d total, %d stale\n" "$transient_count" "$stale_count"
if (( stale_count > 0 )); then
  printf "  ${YEL}WARN${RST}: %d transient doc(s) older than 30 days — review for cleanup\n" "$stale_count"
fi

exit $exit_code
