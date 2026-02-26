# Supervisor Prototype Observability Requirements

Minimum observability outputs required from the supervisor prototype,
aligned with AUTO-M1 restart milestone goals.

## Human-readable outputs

### `supervisor.sh status`

Must display per-process:

- [ ] Process name (`manager`, `claude`, `gemini`, `watchdog`)
- [ ] Status (`running`, `stopped`, `dead`)
- [ ] PID (numeric or `-` if stopped)
- [ ] Restart count (from `.restarts` file)

Example:
```
Autopilot supervisor status
Project: /path/to/claude-multi-ai
PID dir: .autopilot-pids
Log dir: .autopilot-logs

  manager     running   pid=12345     restarts=0
  claude      running   pid=12346     restarts=0
  gemini      dead      pid=99999     restarts=0
  watchdog    stopped   pid=-         restarts=0
```

### Supervisor logs

Each process captures stdout/stderr to `supervisor-{name}.log`:

- [ ] Log files created on `start`
- [ ] Contains loop script output (timestamps, cycle markers)
- [ ] Includes error output from CLI failures
- [ ] Preserved after `stop` (only removed by `clean`)

### Per-cycle logs

Loop scripts produce per-iteration log files:

- [ ] Manager: `manager-YYYY-MM-DD-HHMMSS.log`
- [ ] Workers: `{agent}-YYYY-MM-DD-HHMMSS.log`
- [ ] Watchdog: `watchdog-YYYY-MM-DD-HHMMSS.jsonl`
- [ ] Auto-pruned by `--max-logs` threshold

## Machine-readable outputs

### PID files

- [ ] `.autopilot-pids/{name}.pid` — numeric PID, one per line
- [ ] `.autopilot-pids/{name}.restarts` — restart counter, one per line
- [ ] Parseable by `cat` and shell arithmetic

### Watchdog JSONL

- [ ] One JSON object per line
- [ ] Required fields: `timestamp`, `kind`, `detail`
- [ ] Event kinds: `stale_task`, `state_corruption_detected`
- [ ] Parseable by `jq` and Python `json.loads()`

### Log check output

- [ ] `log_check.sh` validates JSONL well-formedness
- [ ] `--strict` mode exits non-zero on any problem
- [ ] Reports file name and line number for malformed entries

## Baseline from existing autopilot logs

Current logs provide:

| Source | Format | Location |
|--------|--------|----------|
| Manager cycle | Plain text with timestamps | `.autopilot-logs/manager-*.log` |
| Worker cycle | Plain text with CLI output | `.autopilot-logs/{agent}-*.log` |
| Watchdog cycle | JSONL events | `.autopilot-logs/watchdog-*.jsonl` |
| Supervisor process | Plain text (nohup capture) | `.autopilot-logs/supervisor-*.log` |

## Gaps (not yet implemented)

| Gap | Impact | Planned fix |
|-----|--------|-------------|
| No JSON status output | Scripts must parse text output | Future `--json` flag on `status` |
| No per-task timing | Cannot measure task duration from logs | Phase C task leases add timing |
| No heartbeat visibility | Cannot see last heartbeat from supervisor | Phase B instance-aware presence |
| No health endpoint | No HTTP/socket for external monitoring | Phase F supervisor runtime |
| Restart counter always 0 | Cannot track actual restarts | AUTO-M1-CORE-03 auto-restart |

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Status output format
- [supervisor-state-directory-layout.md](supervisor-state-directory-layout.md) — File layout
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) — JSONL event schema
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Known gaps
