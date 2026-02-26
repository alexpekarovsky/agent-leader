# Autopilot Documentation Index

Operator landing page for the headless multi-agent autopilot system. Start with the quickstart, then refer to specific docs as needed.

## Getting Started

| Doc | Purpose |
|-----|---------|
| [quickstart-headless-mvp.md](quickstart-headless-mvp.md) | 7-step guide to launch your first autopilot session |
| [headless-mvp-architecture.md](headless-mvp-architecture.md) | Component diagram, data flow, and MVP limitations |
| [tmux-vs-supervisor.md](tmux-vs-supervisor.md) | Choose between tmux and supervisor runtimes |

## Operations

| Doc | Purpose |
|-----|---------|
| [operator-runbook.md](operator-runbook.md) | Launch, restart, inspect logs, recover stale tasks, shut down |
| [troubleshooting-autopilot.md](troubleshooting-autopilot.md) | Symptom/cause/action tables for common issues |
| [log-file-taxonomy.md](log-file-taxonomy.md) | Log filename patterns, JSONL diagnostics, and review order |
| task-queue-hygiene.md | Cancel mistaken tasks, bulk cleanup, deduplication |

## Supervisor

| Doc | Purpose |
|-----|---------|
| [supervisor-cli-spec.md](supervisor-cli-spec.md) | Command interface: start, stop, status, restart, clean |
| supervisor-test-plan.md | Manual test scenarios and failure injection checklist |
| [tmux-pane-cheatsheet.md](tmux-pane-cheatsheet.md) | tmux pane layout and keyboard shortcuts |

## Multi-Session and Scaling

| Doc | Purpose |
|-----|---------|
| [dual-cc-operation.md](dual-cc-operation.md) | Running two Claude Code sessions — collision analysis and strategies |
| [dual-cc-conventions.md](dual-cc-conventions.md) | Session labels, report prefixes, and claim etiquette |
| [swarm-mode.md](swarm-mode.md) | Prerequisites for multi-instance swarm operation |

## Architecture and Roadmap

| Doc | Purpose |
|-----|---------|
| [roadmap.md](roadmap.md) | Full architecture roadmap: Phases A through D |
| [headless-mvp-architecture.md](headless-mvp-architecture.md) | Current MVP component overview and data boundaries |
