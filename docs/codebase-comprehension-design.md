# Design: Codebase Comprehension Task Type

This document outlines the design for a new `comprehend_project` task type in the `agent-leader` orchestrator. This will enable a team of agents to collaboratively analyze a codebase and produce a shared understanding before detailed planning and implementation begins.

## 1. New Task Type: `comprehend_project`

A new workstream and task type will be introduced to represent this phase.

- **Workstream:** `comprehension`
- **Task Title Convention:** `Comprehend Project: <project_name>`
- **Acceptance Criteria (Template):**
  - "Key modules and their responsibilities identified."
  - "Data models and their relationships mapped."
  - "Entry points for major user flows documented."
  - "Summary report of architectural patterns and dependencies produced."

When the manager creates a `comprehend_project` task, it will also create several sub-tasks, one for each agent in the team, with a specific area of focus.

## 2. Parallel Worker Workflow

1.  **Task Creation:** The manager creates the main `comprehend_project` task and sub-tasks for each agent (e.g., `Comprehend DB Schema`, `Comprehend API Surface`, `Comprehend Frontend Components`).
2.  **Parallel Execution:** Each agent claims their assigned sub-task and begins analyzing their assigned area of the codebase. They can use tools like `glob`, `grep`, and `read_file` to explore the code.
3.  **Individual Reports:** Each agent produces a markdown report summarizing their findings and saves it to a shared location (e.g., `state/comprehension_reports/{task_id}-{agent}.md`).
4.  **Report Submission:** Agents submit their report by calling `orchestrator_submit_report` with the path to their report as an artifact.

## 3. Report Aggregation

Once all sub-tasks for a `comprehend_project` task are `reported`, the manager will trigger a special aggregation step.

1.  **Aggregation Trigger:** The manager detects that all comprehension sub-tasks are complete.
2.  **Aggregation Task:** A new task is created and assigned to the leader (or a designated "synthesis" agent) with the title `Synthesize Comprehension Reports`.
3.  **Synthesis:** The assigned agent reads all the individual reports from `state/comprehension_reports/` and produces a single, unified `CODEBASE_OVERVIEW.md` document. This document contains a holistic summary of the project's architecture, dependencies, and key components.
4.  **Final Report:** The synthesis agent submits the `CODEBASE_OVERVIEW.md` as the final deliverable for the main `comprehend_project` task.

## 4. MCP Tool Changes

### 4.1 New Tool: `orchestrator_initiate_comprehension`
- **Description:** A convenience tool for the manager to create the main `comprehend_project` task and its sub-tasks in one go.
- **Arguments:**
  - `project_name` (string, required)
  - `areas_of_focus` (list of strings, required): e.g., `["Database", "API", "Frontend"]`
- **Returns:** The created parent task and a list of the created sub-tasks.

### 4.2 `orchestrator_create_task` (Enhancement)
- The `create_task` tool will be enhanced to support a `parent_task_id` argument, allowing for the explicit creation of sub-tasks.

### 4.3 `orchestrator_list_sub_tasks` (New Tool)
- **Description:** Retrieves all sub-tasks for a given parent task.
- **Arguments:**
  - `parent_task_id` (string, required)
- **Returns:** A list of task objects.
