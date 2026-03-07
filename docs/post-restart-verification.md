# Post-Restart Verification

This document defines the post-restart validation path and links to `restart-milestone-checklist`.

## Flowchart

Step 1 -> Step 2 -> Step 3 -> Step 4 -> Step 5

- Step 1: Stop current loops and ensure clean baseline.
- Step 2: Clean stale PID/log artifacts.
- Step 3: Start supervisor with intended leader/team routing.
- Step 4: Validate status plus team-scoped task visibility.
- Step 5: Run smoke claim/report cycle and capture evidence.

## Step-by-Step Table

| Step | Command | Expected |
|---|---|---|
| Step 1 | `supervisor.sh stop` | all processes stopped |
| Step 2 | `supervisor.sh clean` | stale artifacts removed |
| Step 3 | `supervisor.sh start ...` | manager/wingman/workers active |
| Step 4 | `supervisor.sh status` + task listing | team filters return expected rows |
| Step 5 | smoke cycle | claim/report pipeline completes |
