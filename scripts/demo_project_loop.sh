#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POLICY_PATH="${1:-$ROOT_DIR/config/policy.codex-manager.json}"

rm -rf "$ROOT_DIR/bus" "$ROOT_DIR/state" "$ROOT_DIR/decisions"

run_cli() {
  python3 -m orchestrator.cli --policy "$POLICY_PATH" --root "$ROOT_DIR" "$@"
}

echo "[1/8] bootstrap"
run_cli bootstrap

echo "[2/8] create backend task (Claude)"
BACKEND_JSON=$(run_cli create-task --title "Build auth backend" --workstream backend --accept "Backend tests pass")
BACKEND_TASK_ID=$(printf '%s' "$BACKEND_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf '%s\n' "$BACKEND_JSON"

echo "[3/8] create frontend task (Gemini)"
FRONTEND_JSON=$(run_cli create-task --title "Build checkout frontend" --workstream frontend --accept "Frontend tests pass")
FRONTEND_TASK_ID=$(printf '%s' "$FRONTEND_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf '%s\n' "$FRONTEND_JSON"

echo "[4/8] workers submit reports"
cat > "$ROOT_DIR/.tmp.backend.report.json" <<REPORT
{
  "task_id": "$BACKEND_TASK_ID",
  "agent": "claude_code",
  "commit_sha": "backend123",
  "status": "done",
  "test_summary": {"command": "pytest -q", "passed": 25, "failed": 0},
  "notes": "Backend implemented and tested"
}
REPORT

cat > "$ROOT_DIR/.tmp.frontend.report.json" <<REPORT
{
  "task_id": "$FRONTEND_TASK_ID",
  "agent": "gemini",
  "commit_sha": "frontend123",
  "status": "done",
  "test_summary": {"command": "npm test -- --runInBand", "passed": 30, "failed": 1},
  "notes": "Frontend developed and tested"
}
REPORT

run_cli ingest-report --file "$ROOT_DIR/.tmp.backend.report.json"
run_cli ingest-report --file "$ROOT_DIR/.tmp.frontend.report.json"

echo "[5/8] manager validates backend pass"
run_cli validate --task-id "$BACKEND_TASK_ID" --pass --notes "All checks passed"

echo "[6/8] manager validates frontend fail -> opens bug"
run_cli validate --task-id "$FRONTEND_TASK_ID" --fail --notes "E2E checkout flow failing against backend contract"

echo "[7/8] architecture vote"
run_cli decide-architecture \
  --topic "Checkout API transport" \
  --options REST \
  --options GraphQL \
  --votes '{"codex":"REST","claude_code":"GraphQL","gemini":"REST"}' \
  --rationale '{"codex":"Lower ops complexity","claude_code":"Typed schema","gemini":"Faster feature velocity"}'

echo "[8/8] final state"
run_cli list-tasks
cat "$ROOT_DIR/state/bugs.json"

rm -f "$ROOT_DIR/.tmp.backend.report.json" "$ROOT_DIR/.tmp.frontend.report.json"
