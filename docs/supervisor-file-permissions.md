# Supervisor File Permission and Ownership Checklist

Expected permissions for supervisor logs, PID files, and state files.

## Path checklist

| Path | Type | Required permission | Owner |
|------|------|-------------------|-------|
| `.autopilot-pids/` | Directory | `rwx` (755) | Current user |
| `.autopilot-pids/*.pid` | File | `rw-` (644) | Current user |
| `.autopilot-pids/*.restarts` | File | `rw-` (644) | Current user |
| `.autopilot-logs/` | Directory | `rwx` (755) | Current user |
| `.autopilot-logs/supervisor-*.log` | File | `rw-` (644) | Current user |
| `.autopilot-logs/*-*.log` | File | `rw-` (644) | Current user |
| `.autopilot-logs/*-*.jsonl` | File | `rw-` (644) | Current user |
| `scripts/autopilot/*.sh` | File | `rwx` (755) | Any |

## Common failure symptoms

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `supervisor.sh start` fails silently | PID dir not writable | `chmod 755 .autopilot-pids` |
| No log files after start | Log dir not writable | `chmod 755 .autopilot-logs` |
| `Permission denied` on loop script | Script not executable | `chmod +x scripts/autopilot/*.sh` |
| Status shows wrong data | PID file owned by different user | `chown $USER .autopilot-pids/*.pid` |
| `clean` can't remove files | Files owned by root or another user | `sudo rm` or fix ownership |

## Pre-start verification

```bash
# Check directory permissions
ls -ld .autopilot-pids .autopilot-logs 2>/dev/null

# Check script permissions
ls -l scripts/autopilot/*.sh | head -5

# Create directories if missing
mkdir -p .autopilot-pids .autopilot-logs

# Fix script permissions if needed
chmod +x scripts/autopilot/*.sh
```

## Multi-user environments

If multiple users run the supervisor on the same machine:

- Use separate `--pid-dir` and `--log-dir` per user
- Or use a shared directory with group write permissions (`chmod 775`)
- Never share PID files between users — PID namespaces differ

## Remediation steps

### Can't write PID files

```bash
# Check ownership
ls -la .autopilot-pids/

# Fix ownership
chown -R $USER .autopilot-pids/

# Or use a different directory
./scripts/autopilot/supervisor.sh start --pid-dir /tmp/$USER-pids
```

### Can't write log files

```bash
# Check ownership
ls -la .autopilot-logs/

# Fix ownership
chown -R $USER .autopilot-logs/

# Or use a different directory
./scripts/autopilot/supervisor.sh start --log-dir /tmp/$USER-logs
```

### Script not executable

```bash
chmod +x scripts/autopilot/supervisor.sh
chmod +x scripts/autopilot/manager_loop.sh
chmod +x scripts/autopilot/worker_loop.sh
chmod +x scripts/autopilot/watchdog_loop.sh
chmod +x scripts/autopilot/monitor_loop.sh
```

## References

- [supervisor-state-directory-layout.md](supervisor-state-directory-layout.md) — Directory layout
- [supervisor-troubleshooting.md](supervisor-troubleshooting.md) — Troubleshooting guide
- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Command reference
