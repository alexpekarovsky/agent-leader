#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY_PATH="${1:-$ROOT_DIR/config/policy.codex-manager.json}"

run_cli() {
  python3 -m orchestrator.cli --policy "$POLICY_PATH" --root "$ROOT_DIR" "$@"
}

# Clean runtime state for a fresh sprint
rm -rf "$ROOT_DIR/bus" "$ROOT_DIR/state" "$ROOT_DIR/decisions"

log() { echo "[live-sprint] $*"; }

log "bootstrap orchestrator"
run_cli bootstrap >/dev/null

log "create backend task (Claude Code)"
BACKEND_JSON=$(run_cli create-task --title "Implement backend order API" --workstream backend --accept "Backend unit tests pass" --accept "Contract tests pass")
BACKEND_TASK_ID=$(printf '%s' "$BACKEND_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

log "create frontend task (Gemini)"
FRONTEND_JSON=$(run_cli create-task --title "Implement checkout frontend" --workstream frontend --accept "Frontend tests pass" --accept "E2E checkout pass")
FRONTEND_TASK_ID=$(printf '%s' "$FRONTEND_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

log "workers submit first reports"
cat > "$ROOT_DIR/.tmp.backend.r1.json" <<REPORT
{
  "task_id": "$BACKEND_TASK_ID",
  "agent": "claude_code",
  "commit_sha": "beefcafe1",
  "status": "done",
  "test_summary": {"command": "pytest -q", "passed": 36, "failed": 0},
  "artifacts": ["backend/orders.py", "backend/tests/test_orders.py"],
  "notes": "developed and tested"
}
REPORT

cat > "$ROOT_DIR/.tmp.frontend.r1.json" <<REPORT
{
  "task_id": "$FRONTEND_TASK_ID",
  "agent": "gemini",
  "commit_sha": "facefeed1",
  "status": "done",
  "test_summary": {"command": "npm test -- --runInBand", "passed": 44, "failed": 0},
  "artifacts": ["frontend/src/checkout.tsx", "frontend/src/checkout.test.tsx"],
  "notes": "developed and tested"
}
REPORT

run_cli ingest-report --file "$ROOT_DIR/.tmp.backend.r1.json" >/dev/null
run_cli ingest-report --file "$ROOT_DIR/.tmp.frontend.r1.json" >/dev/null

log "manager validation: backend pass, frontend fail"
run_cli validate --task-id "$BACKEND_TASK_ID" --pass --notes "backend checks green" >/dev/null
FAIL_OUT=$(run_cli validate --task-id "$FRONTEND_TASK_ID" --fail --notes "E2E failed: checkout payload mismatch")
BUG_ID=$(printf '%s' "$FAIL_OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("bug_id",""))')

log "frontend worker fixes bug and resubmits"
cat > "$ROOT_DIR/.tmp.frontend.r2.json" <<REPORT
{
  "task_id": "$FRONTEND_TASK_ID",
  "agent": "gemini",
  "commit_sha": "facefeed2",
  "status": "done",
  "test_summary": {"command": "npm test && npm run test:e2e", "passed": 52, "failed": 0},
  "artifacts": ["frontend/src/checkout.tsx", "frontend/e2e/checkout.spec.ts"],
  "notes": "bug fixed and retested"
}
REPORT
run_cli ingest-report --file "$ROOT_DIR/.tmp.frontend.r2.json" >/dev/null
run_cli validate --task-id "$FRONTEND_TASK_ID" --pass --notes "frontend checks green after fix" >/dev/null

log "record architecture consensus"
run_cli decide-architecture \
  --topic "Checkout API format" \
  --options REST \
  --options GraphQL \
  --votes '{"codex":"REST","claude_code":"REST","gemini":"GraphQL"}' \
  --rationale '{"codex":"delivery speed","claude_code":"compatibility","gemini":"schema ergonomics"}' >/dev/null

log "final summary"
python3 - <<'PY'
import json
from pathlib import Path
root = Path('.').resolve()
tasks = json.loads((root / 'state' / 'tasks.json').read_text())
bugs = json.loads((root / 'state' / 'bugs.json').read_text())
open_bugs = [b for b in bugs if b.get('status') == 'open']
print(json.dumps({
  "tasks_total": len(tasks),
  "tasks_done": sum(1 for t in tasks if t.get('status') == 'done'),
  "tasks_not_done": [t['id'] for t in tasks if t.get('status') != 'done'],
  "bugs_total": len(bugs),
  "open_bugs": [b['id'] for b in open_bugs],
}, indent=2))
PY

rm -f "$ROOT_DIR/.tmp.backend.r1.json" "$ROOT_DIR/.tmp.frontend.r1.json" "$ROOT_DIR/.tmp.frontend.r2.json"
log "completed"
