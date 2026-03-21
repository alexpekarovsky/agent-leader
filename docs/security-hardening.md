# Security Hardening & Least-Privilege Deployment Guide

This guide covers the agent-leader security model, recommended file permissions,
secrets handling, sandbox mode, and agent identity trust boundaries.

## 1. Directory Permissions

The orchestrator uses four runtime directories. Default permissions after install
are `755` (owner read/write/execute, group and others read/execute). For
production or shared-machine deployments, restrict to owner-only:

| Directory | Contents | Recommended Mode |
|-----------|----------|-----------------|
| `state/` | `tasks.json`, `agents.json`, `blockers.json`, lock files, claim overrides | `700` |
| `bus/` | `events.jsonl`, `audit.jsonl`, reports, commands | `700` |
| `.autopilot-logs/` | Watchdog JSONL, archive, per-task command output | `700` |
| `.autopilot-pids/` | PID files, restart counters | `700` |

### Apply hardened permissions

```bash
chmod 700 state/ bus/ .autopilot-logs/ .autopilot-pids/
chmod 600 state/*.json state/.*.lock bus/*.jsonl
```

### Why restrict these directories

- `state/` contains the full task graph, agent roster, and role assignments.
  An attacker with read access can enumerate active agents, pending tasks, and
  blocker details. Write access allows task injection or status manipulation.
- `bus/audit.jsonl` logs every MCP tool call with arguments — exposing it
  reveals the full operational history.
- PID files can be used to send signals to orchestrator processes if writable.

## 2. MCP Server Process — Least-Privilege Checklist

The MCP server (`orchestrator_mcp_server.py`) runs as a stdio child process
spawned by each CLI. It inherits the CLI process's user/group.

### Recommended setup

1. **Dedicated user (shared machines).**
   On multi-user systems, run the orchestrator under a dedicated non-root user
   (e.g., `agent-leader`) that owns the project directory. Agent CLIs should
   run as that same user or be in a shared group with minimal permissions.

2. **No network listeners.**
   The MCP server communicates exclusively over stdin/stdout JSON-RPC. It opens
   no TCP/UDP ports. No firewall rules are required for the orchestrator itself.

3. **No root required.**
   Never run the orchestrator or agent CLIs as root. The server needs only:
   - Read/write to `state/`, `bus/`, `.autopilot-logs/`, `.autopilot-pids/`
   - Read access to `config/` (policy files)
   - Read access to `orchestrator/` (source)

4. **File locking.**
   The server uses `fcntl` exclusive locks for state consistency. Ensure the
   filesystem supports POSIX advisory locks (local filesystems do; some NFS
   mounts do not). If `fcntl` is unavailable, the server logs a warning and
   continues with degraded multi-process safety.

5. **Binding validation (shared installs).**
   When the MCP server is installed to `~/.local/share/agent-leader/current`,
   binding safety is enforced by default (`ORCHESTRATOR_ENFORCE_SHARED_BINDING=1`):
   - `ORCHESTRATOR_ROOT` must be set explicitly
   - `ORCHESTRATOR_EXPECTED_ROOT` must match for validation
   - On binding failure, the server enters **degraded mode** and rejects all
     tool calls, preventing silent cross-project leaks

6. **Limit environment variables.**
   Only pass the minimum required env vars to the server process:
   ```
   ORCHESTRATOR_ROOT=/path/to/project
   ORCHESTRATOR_EXPECTED_ROOT=/path/to/project
   ORCHESTRATOR_POLICY=/path/to/policy.json
   ```
   Avoid exporting secrets, API keys, or credentials into the MCP server
   environment — it does not need them.

## 3. Secrets Handling

### Current design: no secrets in orchestrator

The orchestrator deliberately stores **no secrets**:
- No API keys, tokens, or passwords in state files
- No credential storage or management
- No environment variables for authentication

All authentication is delegated to the CLI layers (Codex, Claude, Gemini),
which handle their own API keys and session tokens independently.

### Recommendations

- **Never commit `.env` files** or credentials to the repository.
- **Never pass API keys** via `ORCHESTRATOR_*` environment variables.
- **Audit `bus/audit.jsonl`** periodically — while it contains no secrets by
  design, tool-call arguments could include sensitive data if agents pass it
  through MCP calls.
- **Rotate CLI credentials** according to each provider's recommendations.
  The orchestrator is unaffected by credential rotation since it holds no
  tokens itself.
- **`.mcp.json` files** may contain paths and env vars. If your `.mcp.json`
  contains anything sensitive, ensure it is listed in `.gitignore`.

## 4. Sandbox Mode

Sandbox mode is **not enforced by the orchestrator** — it is a property of
each CLI agent's runtime environment.

### How it works

- Each agent reports `sandbox_mode: true|false` during identity verification
  via `orchestrator_connect_to_leader`.
- The orchestrator records this as metadata but does **not** gate task
  assignment or tool access based on sandbox status.
- Sandbox enforcement is the responsibility of each CLI:
  - **Codex**: sandboxed by default; bypass with `--dangerously-bypass-approvals-and-sandbox`
  - **Claude Code**: approval prompts by default; bypass with `--dangerously-skip-permissions`
  - **Gemini**: approval mode; bypass with `--approval-mode yolo`

### Recommendations

- **Keep sandbox enabled** for all agents in production and shared environments.
- Use no-restrictions modes only in trusted, isolated local environments.
- The orchestrator's `orchestrator_list_agents` tool reports each agent's
  `sandbox_mode` — use this to audit team compliance:
  ```text
  Call orchestrator_list_agents with active_only=true
  ```
  Verify all agents report `sandbox_mode: true` for hardened deployments.

## 5. Agent Identity Verification — Trust Boundaries

### Verification flow

When an agent calls `orchestrator_connect_to_leader`, the orchestrator
performs multi-factor verification:

1. **Identity completeness** — all 9 required fields must be present and non-empty:
   `client`, `model`, `cwd`, `permissions_mode`, `sandbox_mode`, `session_id`,
   `connection_id`, `server_version`, `verification_source`

2. **Heartbeat freshness** — the agent must have a recent heartbeat
   (default: within 10 minutes, configurable via policy `heartbeat_timeout_minutes`)

3. **Project root match** — the agent's reported `project_root` or `cwd` must
   resolve to the orchestrator's root directory

4. **Source-agent match** — the `source` parameter must equal the `agent`
   parameter to prevent impersonation

5. **Role validation** — only the current leader can connect with `manager` role

### Trust boundaries

```
┌─────────────────────────────────────────────────────┐
│                   TRUST BOUNDARY                     │
│                                                      │
│  Orchestrator trusts:                                │
│  ├─ Agent self-reported identity fields              │
│  ├─ CLI-reported sandbox_mode and permissions_mode   │
│  └─ Agent-reported cwd/project_root                  │
│                                                      │
│  Orchestrator verifies:                              │
│  ├─ All 9 identity fields present                    │
│  ├─ Heartbeat within staleness window                │
│  ├─ project_root resolves to orchestrator root       │
│  ├─ source == agent (no cross-agent spoofing)        │
│  └─ Role claims match current role assignments       │
│                                                      │
│  Orchestrator does NOT verify:                       │
│  ├─ Agent binary authenticity                        │
│  ├─ Whether sandbox_mode is actually enforced        │
│  ├─ Whether the reported model is the real model     │
│  └─ Network-level transport integrity (stdio only)   │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### Key implications

- **Self-reported identity is trusted.** A malicious process with access to the
  MCP stdio channel can impersonate any agent by providing the correct fields.
  Mitigation: restrict filesystem access to the MCP server binary and state
  directories.

- **Project isolation depends on policy.** The `allow_cross_project_agents`
  policy flag controls whether agents from other project roots can connect:
  - `policy.strict-qa.json`: `false` — agents must match project root
  - Other policies: `true` — cross-project agents allowed
  Use strict-qa policy for production deployments that require project isolation.

- **All agents verified equally.** Every agent — Codex, Claude Code, and
  Gemini — must provide all 9 identity fields. There is no auto-fill or
  relaxed verification for any agent type. Ensure all agents provide
  complete identity payloads.

- **Stale agent window.** Agents are considered active for up to 10 minutes
  (600 seconds) after their last heartbeat. During this window, a disconnected
  agent's identity remains valid. For tighter security, reduce
  `heartbeat_timeout_minutes` in your policy.

## 6. Policy Selection for Security

| Policy | Cross-Project | Use Case |
|--------|:------------:|----------|
| `policy.strict-qa.json` | No | Production, compliance-sensitive environments |
| `policy.balanced.json` | Yes | Development with moderate guardrails |
| `policy.codex-manager.json` | Yes | Default development workflow |
| `policy.prototype-fast.json` | Yes | Rapid prototyping, trusted local only |

### Security-relevant policy triggers

```json
{
  "allow_cross_project_agents": false,
  "stop_on_integrity_mismatch": true,
  "auto_open_bug_on_validation_failure": true,
  "stop_max_open_bugs": 5,
  "stop_max_validation_failures_per_task": 3
}
```

## 7. Audit Trail

The orchestrator maintains append-only audit logs:

| File | Contents |
|------|----------|
| `bus/audit.jsonl` | Every MCP tool call with arguments and results |
| `bus/events.jsonl` | All collaboration events (connections, heartbeats, task state changes) |
| `state/install_audit.jsonl` | Installer operations |

### Audit recommendations

- **Protect audit files** — set `chmod 600 bus/audit.jsonl bus/events.jsonl`
- **Monitor audit size** — `audit.jsonl` grows continuously; implement log
  rotation via `scripts/autopilot/log_check.sh` or external tooling
- **No audit signing** — events are appended without cryptographic signatures;
  a process with write access could modify the log. For tamper-evidence,
  consider shipping logs to an external append-only store
- **Query audits via MCP**:
  ```text
  Call orchestrator_list_audit_logs with limit=200 tool="orchestrator_connect_to_leader"
  ```

## 8. Deployment Hardening Checklist

- [ ] Run orchestrator and agents as non-root dedicated user
- [ ] Set `chmod 700` on `state/`, `bus/`, `.autopilot-logs/`, `.autopilot-pids/`
- [ ] Set `chmod 600` on all `.json`, `.jsonl`, and `.lock` files in those dirs
- [ ] Use `policy.strict-qa.json` for production (`allow_cross_project_agents: false`)
- [ ] Verify all agents report `sandbox_mode: true` via `orchestrator_list_agents`
- [ ] Set `ORCHESTRATOR_ENFORCE_SHARED_BINDING=1` (default) for shared installs
- [ ] Pass only required env vars (`ORCHESTRATOR_ROOT`, `ORCHESTRATOR_EXPECTED_ROOT`, `ORCHESTRATOR_POLICY`)
- [ ] Ensure `.mcp.json` is in `.gitignore` if it contains environment-specific paths
- [ ] Set up log rotation for `bus/audit.jsonl` (grows unbounded)
- [ ] Review `bus/audit.jsonl` periodically for unexpected tool-call patterns
- [ ] Reduce `heartbeat_timeout_minutes` in policy if tighter staleness detection is needed
- [ ] Verify filesystem supports POSIX `fcntl` advisory locks
