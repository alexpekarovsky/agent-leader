# tmux Pane & Session Cheat Sheet

Quick reference for identifying which pane runs which role during an
autopilot `team_tmux.sh` session.

## Session layout

`team_tmux.sh` creates session **`agents-autopilot`** (configurable via
`--session`) with two windows:

### Window 0: `manager` (tiled 2×2 layout)

| Pane | Index | Role | Script |
|------|-------|------|--------|
| Top-left | `0` | Manager (codex) | `manager_loop.sh --cli codex` |
| Top-right | `1` | Claude worker | `worker_loop.sh --cli claude --agent claude_code` |
| Bottom-right | `2` | Gemini worker | `worker_loop.sh --cli gemini --agent gemini` |
| Bottom-left | `3` | Watchdog | `watchdog_loop.sh` |

> Pane numbering follows tmux split order: the first split (`split-window -h`)
> creates pane 1 to the right of 0, then vertical splits add panes 2 and 3.
> `select-layout tiled` rearranges them into a 2×2 grid.

### Window 1: `monitor`

| Pane | Index | Role | Script |
|------|-------|------|--------|
| Full window | `0` | Monitor | `monitor_loop.sh <project-root> 10` |

## Inspect pane output

```bash
# Show live output of a specific pane (Ctrl-C to stop)
tmux capture-pane -t agents-autopilot:manager.0 -p      # manager
tmux capture-pane -t agents-autopilot:manager.1 -p      # claude worker
tmux capture-pane -t agents-autopilot:manager.2 -p      # gemini worker
tmux capture-pane -t agents-autopilot:manager.3 -p      # watchdog
tmux capture-pane -t agents-autopilot:monitor.0 -p      # monitor

# Capture full scrollback to a file
tmux capture-pane -t agents-autopilot:manager.0 -pS - > /tmp/manager.txt
```

## Attach to the session

```bash
tmux attach -t agents-autopilot                # attach to default window
tmux attach -t agents-autopilot:monitor        # attach directly to monitor
```

## Restart a single role

Kill and respawn one pane without tearing down the whole session:

```bash
# Example: restart the claude worker (pane 1)
tmux respawn-pane -k -t agents-autopilot:manager.1 \
  "cd /path/to/project && ./scripts/autopilot/worker_loop.sh \
    --cli claude --agent claude_code \
    --project-root /path/to/project \
    --interval 25 --cli-timeout 600 \
    --log-dir /path/to/project/.autopilot-logs"

# Example: restart the watchdog (pane 3)
tmux respawn-pane -k -t agents-autopilot:manager.3 \
  "cd /path/to/project && ./scripts/autopilot/watchdog_loop.sh \
    --project-root /path/to/project \
    --interval 15 \
    --log-dir /path/to/project/.autopilot-logs"
```

Replace `/path/to/project` with your actual `--project-root` value.

## Tear down the session

```bash
tmux kill-session -t agents-autopilot
```

## Previewing without tmux

Use `--dry-run` to see the full session plan without creating anything:

```bash
./scripts/autopilot/team_tmux.sh --dry-run
```

This prints every `tmux` command that would run, including configured
timeouts and intervals. See `team_tmux.sh` and `monitor_loop.sh` for
the underlying scripts.
