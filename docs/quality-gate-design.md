# Design: Automated Quality Gate System

This document outlines the design for a Plankton-style automated quality gate system within the `agent-leader` orchestrator. The goal is to automatically check for common issues before a pull request is created, providing fast feedback to the agent.

## 1. Quality Gate Checks

The quality gate will consist of several automated checks that run when an agent signals its intent to create a pull request (e.g., via a new `orchestrator_propose_pr` tool).

### 1.1 Static Analysis Checks
- **Style Violations:** Run a linter (e.g., `ruff`, `eslint`) to check for style guide violations.
- **Code Patterns:** Use a tool like `grep` or a custom script to search for known bad patterns (e.g., `TODO`s without a ticket number, placeholder comments).

### 1.2 Test Coverage Checks
- **Missing Tests:** Check if new code files have corresponding test files. This can be a simple convention-based check (e.g., `src/my_new_feature.py` should have a corresponding `tests/test_my_new_feature.py`).
- **Test Execution:** Run the project's test suite to ensure all tests pass.

### 1.3 Architectural Checks
- **Dependency Violations:** Check for illegal imports between layers or modules. This can be implemented with a custom script that analyzes the import graph.
- **Contract Mismatches:** If the project uses a schema-based approach (e.g., OpenAPI, gRPC), this check would verify that the code implements the specified contracts.

## 2. Triggers and Workflow

1.  **Agent proposes a PR:** The agent calls a new `orchestrator_propose_pr` tool with the commit SHA and a preliminary PR title/body.
2.  **Quality Gate is triggered:** The MCP server receives this call and triggers the quality gate checks in the background.
3.  **Violations are reported:**
    *   If any checks fail, the orchestrator creates a new "quality_violation" object (similar to a bug or blocker) and returns it to the agent. The PR is not created.
    *   The violation object contains details about the failed checks and suggested remediation steps.
4.  **Agent addresses violations:** The agent receives the violation report, addresses the issues in a new commit, and re-proposes the PR.
5.  **PR is created:** Once all quality gate checks pass, the orchestrator proceeds to create the pull request using the `orchestrator_create_github_pr` tool (as designed in `docs/github-integration-design.md`).

## 3. MCP Tool and Data Model Changes

### 3.1 New Tool: `orchestrator_propose_pr`
- **Description:** Signals intent to create a PR and triggers the quality gate.
- **Arguments:**
  - `task_id` (string, required)
  - `commit_sha` (string, required)
  - `title` (string, required)
  - `body` (string)
- **Returns:** A status object indicating whether the proposal was accepted (and the PR created) or rejected (with a list of violations).

### 3.2 New Data Model: `quality_violations.json`
```json
{
  "id": "QV-9999",
  "task_id": "TASK-abcdef",
  "commit_sha": "...",
  "check_name": "Missing Tests",
  "details": "The file 'src/new_feature.py' was added, but no corresponding test file was found.",
  "remediation": "Create a new test file at 'tests/test_new_feature.py' and add tests for the new functionality.",
  "status": "open",
  "created_at": "..."
}
```
