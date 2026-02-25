# Autopilot Test Suite Map

Quick reference mapping every test file and smoke-test section to the
behavior it covers.  Use this to spot coverage gaps and avoid duplicate
work when adding new tests.

## Python unit tests (`tests/`)

| File | Tests | Behaviors covered |
|------|------:|-------------------|
| `test_orchestrator_reliability.py` | 25 | Event bus reliability, agent listing side-effects, task status guards, connect/identity verification, role authorization, presence refresh, end-to-end workflow (5-iteration + multi-process), CLI timeout markers in common.sh / manager_loop / worker_loop |
| `test_task_rollback.py` | 6 | Task blocking/cancellation, correction events, blocked tasks not reassigned, deduplication keeps oldest, bulk cancellation, claim skips blocked |
| `test_team_tmux_dryrun.py` | 9 | Dry-run exit code, default/custom session name, custom manager/worker CLI timeouts, timeout independence, default timeout values, all tmux commands present, log-dir propagation |
| `test_monitor_loop_smoke.py` | 5 | Project header output, missing logs dir, empty logs dir, log file listing, bounded runtime |
| `test_manager_loop_args.py` | 4 | Unknown-arg rejection (exit code, error text, ERROR level, first-arg rejection) |
| `test_worker_loop_args.py` | 4 | Unknown-arg rejection (exit code, error text, ERROR level, first-arg rejection) |

**Run:** `python3 -m unittest discover tests -v`

## Shell smoke tests (`scripts/autopilot/smoke_test.sh`)

| # | Name | Behaviors covered |
|---|------|-------------------|
| 1 | team_tmux.sh --dry-run | Renders tmux plan, shows session metadata |
| 2 | manager_loop.sh --once timeout | Stub CLI timeout, log file creation, timeout marker |
| 3 | worker_loop.sh --once timeout | Stub CLI timeout, log file creation, timeout marker |
| 4 | watchdog_loop.sh --once | JSONL file emission, stale-task detection, state-corruption detection |
| 5 | prune_old_logs | Excess log file removal |
| 6 | tmux live launch/teardown | Real session creation, pane count, monitor window, teardown (skipped without tmux) |
| 7 | Log retention --max-logs | Log pruning under repeated loop runs |
| 8 | log_check.sh strict mode | Valid JSONL passes, malformed JSONL fails, non-strict mode tolerates errors |
| 9 | README command validation | team_tmux --dry-run, smoke_test, log_check, supervisor status |
| 10 | Dry-run timeout/session propagation | Custom session name, manager/worker CLI timeouts, log-dir in all commands, timeout isolation, all 6 tmux commands |
| 11 | Operator runbook command sequence | Runbook-documented commands execute correctly |
| 12 | Log taxonomy filename patterns | Log filenames match documented naming conventions |
| 13 | Dual-CC conventions doc examples | Documented examples in dual-CC conventions are valid |
| 14 | Docs index link validation | Internal doc links resolve correctly |

**Run:** `bash scripts/autopilot/smoke_test.sh`

## Coverage matrix by component

| Component | Python tests | Smoke tests |
|-----------|-------------|-------------|
| `team_tmux.sh` | dry-run output, timeouts, session name | dry-run (#1, #10), live tmux (#6) |
| `manager_loop.sh` | unknown-arg rejection, CLI timeout | timeout (#2), log retention (#7) |
| `worker_loop.sh` | unknown-arg rejection, CLI timeout | timeout (#3), log retention (#7) |
| `watchdog_loop.sh` | — | JSONL emission (#4), stale-task detection (#4) |
| `monitor_loop.sh` | project header, missing/empty logs | — |
| `common.sh` | `run_cli_prompt` timeout + marker | (indirectly via #2, #3) |
| `log_check.sh` | — | strict/non-strict validation (#8) |
| `prune_old_logs` | — | excess file removal (#5) |
| Orchestrator engine | workflow, status guards, roles, connect, events, presence | — |
| Task rollback | blocking, cancellation, dedup | — |

## Known coverage gaps

- **watchdog_loop.sh** has no Python unit tests (only shell smoke tests)
- **log_check.sh** has no Python unit tests
- **prune_old_logs** has no Python unit tests
- **supervisor.sh** has no dedicated test file (only README validation in smoke #9)
- **common.sh** helper functions (`sleep_with_jitter`, `mkdir_logs`, `require_cmd`) are not directly unit-tested
- **monitor_loop.sh** has no shell smoke test coverage

## Updating this document

When adding a new test file or smoke-test section, add a row to the
relevant table and update the coverage matrix.  Keep the gap list
current so future tasks can target uncovered areas.
