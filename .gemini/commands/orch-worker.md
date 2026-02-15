Worker loop command:

1. Call orchestrator_claim_next_task(agent=gemini)
2. Implement task scope
3. Run tests
4. Commit
5. Call orchestrator_submit_report with commit + tests
6. Ask manager to validate
