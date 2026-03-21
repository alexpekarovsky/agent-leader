# Design: Stacked PR Support

Extends the GitHub integration to support dependent PR chains where a
multi-part feature is delivered as an ordered sequence of pull requests, each
targeting the branch of the previous PR in the stack.

## 1. Motivation

Large features often span multiple logical changes.  Stacking PRs keeps each
review focused while preserving merge order:

1. `main ← feature/step-1` — foundation
2. `feature/step-1 ← feature/step-2` — builds on step 1
3. `feature/step-2 ← feature/step-3` — final layer

The orchestrator needs to track this chain so agents can:

- Create PRs with correct base branches automatically.
- Gate child PRs until their parent merges.
- React to merge events to ungate and rebase the next PR.
- Report stack-level progress alongside individual task status.

## 2. Data Model

### 2.1 PR Stack (`state/pr_stacks.json`)

```json
{
  "id": "STACK-a1b2c3d4",
  "repo": "org/repo",
  "title": "Feature: multi-step auth rewrite",
  "base_branch": "main",
  "state": "open | partially_merged | merged | closed",
  "task_ids": ["TASK-xxx", "TASK-yyy"],
  "prs": [ <ordered list of PR entries> ],
  "created_by": "claude_code",
  "created_at": "...",
  "updated_at": "..."
}
```

### 2.2 Stacked PR Entry (inside `prs` array)

```json
{
  "id": "STPR-e5f6g7h8",
  "stack_id": "STACK-a1b2c3d4",
  "branch": "feature/step-1",
  "base_branch": "main",
  "title": "Step 1: add auth middleware",
  "task_id": "TASK-xxx",
  "pr_number": 42,
  "state": "draft | open | approved | merged | closed",
  "ci_status": "passed | failed | running | null",
  "gated": false,
  "created_at": "...",
  "updated_at": "...",
  "merged_at": null
}
```

**Key invariant:** `prs[i].base_branch == prs[i-1].branch` (or `stack.base_branch` for `i==0`).

## 3. Dependency Gating Rules

| Condition | `gated` | Merge-ready |
|-----------|---------|-------------|
| First PR in stack | `false` | Yes (no parent) |
| Parent state == `merged` | `false` | Yes |
| Parent state != `merged` | `true` | No |

When a PR merges:
1. Mark it `state: "merged"`, set `merged_at`.
2. Ungate the next PR in the chain (`gated: false`).
3. Publish `prstack.pr_ungated` event so agents can rebase/update the child.
4. Update stack state (`partially_merged` or `merged`).

## 4. Integration Points

### 4.1 Engine Methods (orchestrator/engine.py)

- `create_pr_stack(...)` — persist new stack
- `add_pr_to_stack(stack_id, ...)` — append/insert PR entry
- `process_pr_merge(stack_id, pr_id)` — handle merge, ungate children
- `get_pr_stacks(...)` — list/filter stacks
- `get_stack_status(stack_id)` — readiness summary

### 4.2 MCP Tools (future)

| Tool | Description |
|------|-------------|
| `orchestrator_create_pr_stack` | Create a new stack |
| `orchestrator_add_stack_pr` | Add a PR entry |
| `orchestrator_get_stack_status` | Get readiness + gating state |
| `orchestrator_process_stack_merge` | Handle merge webhook for stacked PR |

### 4.3 Event Bus Integration

Events published on stack state changes:

- `prstack.created` — new stack created
- `prstack.pr_added` — PR added to stack
- `prstack.pr_ungated` — child PR unblocked after parent merge
- `prstack.merged` — entire stack merged
- `prstack.closed` — stack closed (all PRs closed/merged)

### 4.4 CI Status Propagation

When a `github.ci_status_updated` event arrives for a branch that belongs to
a stacked PR, the engine updates the PR entry's `ci_status` field.  This
allows quality gates to block merge even when dependency gating passes.

## 5. Dependency on CI/GitHub Integration

This feature builds on the completed `ci-github-integrations` milestone:

- **CI normalization** (`orchestrator/github_ci.py`) — provides `ci_status`
  values for PR entries.
- **Webhook processing** (`orchestrator_process_github_webhook`) — will be
  extended to detect merge events on stacked branches.
- **Task→PR linkage** (`task_id` in PR entries) — reuses the existing
  `external_id` pattern from CI integration.

## 6. Future Work

- **Auto-rebase**: when a parent merges, automatically rebase the child branch.
- **Stack visualization**: TUI dashboard section showing chain progress.
- **Conflict detection**: warn when a parent change introduces conflicts in children.
- **Branch naming convention**: configurable pattern (e.g., `stack/<stack-id>/step-N`).
