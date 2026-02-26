# Status Reporting Cadence and Template Guidance

> Recommended cadence for reporting overall % + AUTO-M1 % during rollout.

## Recommended Cadence

| Trigger | Action | Audience |
|---|---|---|
| Every 10 minutes | Auto-refresh `orchestrator_status` | Automated monitoring |
| Every manager cycle | `live_status_report` update | Manager agent |
| On milestone completion | Full status report | Operator + stakeholders |
| On blocker spike (3+ new) | Alert status update | Operator |
| On agent offline event | Team health update | Operator |

## Template

Use [percent-reporting-template.md](percent-reporting-template.md) with both:
- **Overall project %** — `done / total_tasks × 100`
- **AUTO-M1 milestone %** — `milestone_done / milestone_total × 100`

Always include:
1. Both percentages with definitions
2. Team health (who's active, who's offline)
3. Pipeline indicators (reported, blockers, bugs)
4. Next actions (what's blocking progress)

## Anti-Patterns

| Don't | Why | Do Instead |
|---|---|---|
| Report only overall % | Hides milestone progress | Always show both |
| Skip team health | Hides offline agents | Include team section |
| Report hourly to stakeholders | Too noisy | Report on milestones or daily |
| Omit blocker count | Hides risk | Always show pipeline health |
