# Design: GitHub Integration for Agent Leader

This document outlines the data models and MCP tool surface for integrating GitHub issues, pull requests, and CI results into the `agent-leader` orchestration workflow.

## 1. Data Models

We will introduce new data models to represent GitHub artifacts within the orchestration engine. These will be stored in the `state/` directory, similar to tasks, bugs, and blockers.

### 1.1 GitHub Issue (`state/github_issues.json`)

```json
{
  "id": "GH-ISSUE-1234",
  "task_id": "TASK-abcdef",
  "repo": "example/repo",
  "issue_number": 42,
  "title": "Bug: Users cannot log in",
  "body": "...",
  "state": "open",
  "labels": ["bug", "priority:high"],
  "assignees": ["github-username"],
  "created_at": "...",
  "updated_at": "...",
  "closed_at": "..."
}
```

### 1.2 GitHub Pull Request (`state/github_prs.json`)

```json
{
  "id": "GH-PR-5678",
  "task_id": "TASK-abcdef",
  "repo": "example/repo",
  "pr_number": 88,
  "title": "Fix: Corrects login logic",
  "body": "...",
  "state": "open",
  "branch": "fix/login-bug",
  "base_branch": "main",
  "labels": ["bugfix", "ready-for-review"],
  "assignees": ["github-username"],
  "reviewers": ["other-username"],
  "ci_status": "pending",
  "created_at": "...",
  "updated_at": "...",
  "merged_at": "...",
  "closed_at": "..."
}
```

## 2. MCP Tool Surface

New tools will be added to the MCP to allow agents to interact with these GitHub artifacts.

### 2.1 `orchestrator_create_github_issue`

- **Description:** Creates a new GitHub issue and links it to a task.
- **Arguments:**
  - `task_id` (string, required)
  - `repo` (string, required)
  - `title` (string, required)
  - `body` (string)
  - `labels` (list of strings)
  - `assignees` (list of strings)
- **Returns:** The created GitHub Issue object.

### 2.2 `orchestrator_get_github_issue`

- **Description:** Retrieves a GitHub issue by its number or linked task.
- **Arguments:**
  - `repo` (string, required)
  - `issue_number` (integer)
  - `task_id` (string)
- **Returns:** The GitHub Issue object.

### 2.3 `orchestrator_create_github_pr`

- **Description:** Creates a new GitHub pull request and links it to a task.
- **Arguments:**
  - `task_id` (string, required)
  - `repo` (string, required)
  - `title` (string, required)
  - `body` (string)
  - `branch` (string, required)
  - `base_branch` (string, required)
  - `labels` (list of strings)
  - `assignees` (list of strings)
  - `reviewers` (list of strings)
- **Returns:** The created GitHub PR object.

### 2.4 `orchestrator_get_github_pr`

- **Description:** Retrieves a GitHub PR by its number or linked task.
- **Arguments:**
  - `repo` (string, required)
  - `pr_number` (integer)
  - `task_id` (string)
- **Returns:** The GitHub PR object.

## 3. CI Result Ingestion

CI results will be ingested via a webhook mechanism. A new endpoint will be added to the `orchestrator_mcp_server.py` that listens for incoming webhooks from GitHub Actions (or other CI providers).

- **Endpoint:** `/webhook/ci`
- **Payload:** The standard GitHub `check_suite` or `check_run` webhook payload.
- **Action:** When a `completed` event is received, the server will:
  1. Find the corresponding Pull Request in `state/github_prs.json` (by commit SHA).
  2. Update the `ci_status` field of the PR object (`success`, `failure`, etc.).
  3. Publish a `github.ci_result` event on the bus, allowing agents to react to the new status.
