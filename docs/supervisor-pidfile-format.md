# Supervisor PID File Format Spec

Defines the PID file naming, content conventions, and stale PID handling for the supervisor prototype (`supervisor.sh`).

## File Location

PID files are stored in `.autopilot-pids/` under the project root (configurable via `--pid-dir`).

```
.autopilot-pids/
├── manager.pid        # Manager process ID
├── manager.restarts   # Manager restart count
├── claude.pid         # Claude worker process ID
├── claude.restarts    # Claude restart count
├── gemini.pid         # Gemini worker process ID
├── gemini.restarts    # Gemini restart count
├── watchdog.pid       # Watchdog process ID
└── watchdog.restarts  # Watchdog restart count
```

## Naming Convention

| File pattern | Content | Created by | Removed by |
|-------------|---------|------------|------------|
| `{process}.pid` | Single integer (PID) | `supervisor.sh start` | `supervisor.sh stop` or `clean` |
| `{process}.restarts` | Single integer (count) | `supervisor.sh start` | `supervisor.sh stop` or `clean` |

Process names: `manager`, `claude`, `gemini`, `watchdog`.

## PID File Content

Each `.pid` file contains exactly one line: the process ID of the background job.

```
$ cat .autopilot-pids/manager.pid
12345
```

No trailing newline, no whitespace, no metadata — just the integer PID.

## Restart Counter Content

Each `.restarts` file contains a single integer tracking how many times the process has been restarted. Initialized to `0` on first start.

```
$ cat .autopilot-pids/manager.restarts
0
```

## How PID Files Are Used

### Start

```bash
supervisor.sh start
```

1. For each process, checks if `{process}.pid` exists and the PID is alive (`kill -0`)
2. If alive: skips (idempotent)
3. If not alive or no file: launches the process with `nohup`, writes the new PID

### Stop

```bash
supervisor.sh stop
```

1. Reads PID from `{process}.pid`
2. Sends `SIGTERM` to the process
3. Waits briefly for exit
4. Removes `{process}.pid` and `{process}.restarts`

### Status

```bash
supervisor.sh status
```

1. For each process, reads `{process}.pid`
2. Checks if PID is alive with `kill -0`
3. Reports: `running` (alive), `dead` (PID file exists but process gone), or `stopped` (no PID file)

### Clean

```bash
supervisor.sh clean
```

1. For each process, reads `{process}.pid`
2. If PID is not alive: removes `.pid` and `.restarts` files
3. If PID is alive: warns and skips (must stop first)
4. Removes empty `.autopilot-pids/` directory

## Stale PID Handling

### What makes a PID stale

A PID file is stale when the recorded process ID no longer corresponds to the supervisor's child process:

| Scenario | PID file state | Actual process |
|----------|---------------|----------------|
| Normal running | `12345` | Loop script running as PID 12345 |
| Clean shutdown | File removed | Process exited |
| Crash | `12345` | PID 12345 is dead |
| System reboot | `12345` | PID 12345 may be a different process |

### Detection

```bash
# Check if PID is alive
kill -0 "$(cat .autopilot-pids/manager.pid)" 2>/dev/null
echo $?  # 0 = alive, 1 = dead/stale
```

The `supervisor.sh status` command does this automatically.

### PID reuse after reboot

After a system reboot, the PID recorded in the file may be assigned to a completely different process. The supervisor checks `kill -0` which only confirms *a* process with that PID exists, not that it's the *correct* process.

**Workaround**: Always run `supervisor.sh clean` after a reboot before starting. This removes all PID files regardless of whether the PID appears alive.

```bash
# After reboot:
./scripts/autopilot/supervisor.sh clean
./scripts/autopilot/supervisor.sh start
```

### Manual cleanup

If `supervisor.sh clean` can't remove a file (e.g., permissions issue):

```bash
rm -f .autopilot-pids/*.pid .autopilot-pids/*.restarts
rmdir .autopilot-pids 2>/dev/null
```

## Examples

### Fresh start

```bash
$ ./scripts/autopilot/supervisor.sh start
[INFO] starting all processes (project=/Users/alex/claude-multi-ai)
[INFO] started manager pid=12345 log=.autopilot-logs/supervisor-manager.log
[INFO] started claude pid=12346 log=.autopilot-logs/supervisor-claude.log
[INFO] started gemini pid=12347 log=.autopilot-logs/supervisor-gemini.log
[INFO] started watchdog pid=12348 log=.autopilot-logs/supervisor-watchdog.log

$ ls .autopilot-pids/
claude.pid       claude.restarts  gemini.pid       gemini.restarts
manager.pid      manager.restarts watchdog.pid     watchdog.restarts
```

### Status with one dead process

```bash
$ ./scripts/autopilot/supervisor.sh status
[STATUS] manager: running (pid=12345)
[STATUS] claude: dead (pid=12346 not running)
[STATUS] gemini: running (pid=12347)
[STATUS] watchdog: running (pid=12348)
```

### Clean after crash

```bash
$ ./scripts/autopilot/supervisor.sh clean
[INFO] removed stale pidfile for claude (pid=12346)
Cleaned 1 file(s).
```

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Full command reference (AUTO-M1-OPS-01)
- [supervisor-log-naming.md](supervisor-log-naming.md) — Log file naming conventions
- [supervisor-startup-profiles.md](supervisor-startup-profiles.md) — Startup configuration examples
