# Supervisor Health Snapshot Schema Proposal

JSON schema for a machine-readable health snapshot output from the
supervisor prototype.  Intended for future `supervisor.sh status --json`
support and external monitoring integration.

## Proposed schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["timestamp", "project_root", "pid_dir", "log_dir", "processes"],
  "properties": {
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp of snapshot"
    },
    "project_root": {
      "type": "string",
      "description": "Absolute path to project root"
    },
    "pid_dir": {
      "type": "string",
      "description": "Path to PID file directory"
    },
    "log_dir": {
      "type": "string",
      "description": "Path to log file directory"
    },
    "processes": {
      "type": "array",
      "items": { "$ref": "#/$defs/process_entry" }
    }
  },
  "$defs": {
    "process_entry": {
      "type": "object",
      "required": ["name", "status", "pid", "restarts"],
      "properties": {
        "name": {
          "type": "string",
          "enum": ["manager", "claude", "gemini", "watchdog"],
          "description": "Process role name"
        },
        "status": {
          "type": "string",
          "enum": ["running", "stopped", "dead"],
          "description": "Current process state"
        },
        "pid": {
          "type": ["integer", "null"],
          "description": "Process ID, null if stopped"
        },
        "restarts": {
          "type": "integer",
          "minimum": 0,
          "description": "Restart count from .restarts file"
        },
        "last_task": {
          "type": ["string", "null"],
          "description": "Last known task ID (future, from orchestrator query)"
        },
        "last_heartbeat_seen": {
          "type": ["string", "null"],
          "format": "date-time",
          "description": "Last heartbeat timestamp (future, from orchestrator)"
        },
        "log_file": {
          "type": ["string", "null"],
          "description": "Path to supervisor log for this process"
        },
        "log_size_bytes": {
          "type": ["integer", "null"],
          "description": "Current supervisor log file size"
        }
      }
    }
  }
}
```

## Example output

```json
{
  "timestamp": "2026-02-26T00:25:00Z",
  "project_root": "/Users/alex/claude-multi-ai",
  "pid_dir": ".autopilot-pids",
  "log_dir": ".autopilot-logs",
  "processes": [
    {
      "name": "manager",
      "status": "running",
      "pid": 12345,
      "restarts": 0,
      "last_task": null,
      "last_heartbeat_seen": null,
      "log_file": ".autopilot-logs/supervisor-manager.log",
      "log_size_bytes": 4096
    },
    {
      "name": "claude",
      "status": "running",
      "pid": 12346,
      "restarts": 0,
      "last_task": "TASK-abc123",
      "last_heartbeat_seen": "2026-02-26T00:24:55Z",
      "log_file": ".autopilot-logs/supervisor-claude.log",
      "log_size_bytes": 8192
    },
    {
      "name": "gemini",
      "status": "dead",
      "pid": 99999,
      "restarts": 0,
      "last_task": null,
      "last_heartbeat_seen": null,
      "log_file": ".autopilot-logs/supervisor-gemini.log",
      "log_size_bytes": 512
    },
    {
      "name": "watchdog",
      "status": "stopped",
      "pid": null,
      "restarts": 0,
      "last_task": null,
      "last_heartbeat_seen": null,
      "log_file": null,
      "log_size_bytes": null
    }
  ]
}
```

## Field alignment with restart milestone

| Field | Available now | Source |
|-------|--------------|--------|
| `name` | Yes | Hardcoded process list |
| `status` | Yes | PID file + `kill -0` check |
| `pid` | Yes | PID file content |
| `restarts` | Yes (always 0) | `.restarts` file |
| `last_task` | No | Requires orchestrator query |
| `last_heartbeat_seen` | No | Requires orchestrator query |
| `log_file` | Yes | Derived from `--log-dir` + name |
| `log_size_bytes` | Yes | `stat` on log file |

## Current unknowns and gaps

| Gap | Description | Resolution path |
|-----|-------------|----------------|
| `last_task` source | Supervisor has no MCP access | Add optional orchestrator query or read from event log |
| `last_heartbeat_seen` source | Supervisor doesn't track heartbeats | Query `orchestrator_list_agents` or read agent state file |
| Process start time | Not stored alongside PID | Future: write epoch timestamp to PID file |
| Health check | No active health verification beyond `kill -0` | Future: probe loop script responsiveness |
| Snapshot frequency | One-shot on `status` call | Future: periodic snapshot file for monitoring agents |

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Current status output format
- [supervisor-observability-checklist.md](supervisor-observability-checklist.md) — Observability requirements
- [supervisor-state-directory-layout.md](supervisor-state-directory-layout.md) — File layout
- [watchdog-jsonl-schema.md](watchdog-jsonl-schema.md) — JSONL event schema
