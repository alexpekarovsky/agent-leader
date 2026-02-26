# Supervisor Incident Log Template

Reusable incident log for supervisor process issues. Copy the relevant
template for each incident type and fill in the fields.

## Type 1: Startup failure

Process will not start or dies immediately after start.

```
## Incident: Startup Failure — [DATE HH:MM]
Symptoms: Process=[manager|claude|gemini|watchdog], status=[stopped|dead]

Evidence:
  Supervisor log: [paste last 5 lines of .autopilot-logs/supervisor-{process}.log]
  Direct test:    [paste output of loop script with --once]
  CLI check:      which {cli} && {cli} --version → [paste output]

Root cause: [e.g., CLI not on PATH, missing env var, permission denied]
Resolution: [fix applied] → verified with supervisor.sh start + status
Prevention: [ ] Add CLI check to pre-flight  [ ] Document required env vars
```

## Type 2: Crash loop

Process starts but keeps dying within seconds.

```
## Incident: Crash Loop — [DATE HH:MM]
Symptoms: Process=[manager|claude|gemini|watchdog]
  Restart count: [check .autopilot-pids/{process}.restarts]
  Time alive before crash: [seconds]

Evidence:
  Supervisor log: [paste last 10 lines of supervisor-{process}.log]
  Process log:    [paste last 10 lines of most recent manager/worker log]
  Watchdog:       [paste relevant entries from watchdog-*.jsonl]

Root cause: [e.g., MCP server down, API key expired, state file corrupted]
Resolution: [fix applied] → supervisor.sh stop + start → stays running >60s
Prevention: [ ] Add health check to startup  [ ] Monitor for repeated crashes
```

## Type 3: Stale worker

Worker process appears running but is not making progress.

```
## Incident: Stale Worker — [DATE HH:MM]
Symptoms: Process=[claude|gemini], PID=____, status=running
  Last log output: [timestamp from most recent worker log]
  Task stuck: TASK-________ (in_progress for ______ minutes)

Evidence:
  Supervisor:  [paste supervisor.sh status output]
  Worker log:  [paste last 10 lines of worker-{agent}-*.log]
  Task state:  orchestrator_list_tasks(status="in_progress") → [paste stuck task]
  Watchdog:    [paste stale_task entry from watchdog-*.jsonl]

Root cause: [e.g., CLI hung on large file, API rate limit, infinite test loop]
Resolution: supervisor.sh restart → reassign task (status="assigned") → verify new cycle
Prevention: [ ] Reduce --cli-timeout  [ ] Break large tasks  [ ] Monitor cycle= counter
```

## Incident log

| # | Date | Type | Process | Duration | Root cause (1 line) |
|---|------|------|---------|----------|---------------------|
| 1 |      |      |         |          |                     |
| 2 |      |      |         |          |                     |
| 3 |      |      |         |          |                     |

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) -- Supervisor commands
- [supervisor-crash-loop-runbook.md](supervisor-crash-loop-runbook.md) -- Crash-loop diagnosis
- [monitor-pane-interpretation.md](monitor-pane-interpretation.md) -- Log patterns
- [incident-triage-order.md](incident-triage-order.md) -- Step-by-step triage
