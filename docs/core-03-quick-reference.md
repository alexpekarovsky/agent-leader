# CORE-03 Reviewer Quick Reference

One-screen checklist for reviewing a CORE-03 (lease issuance) acceptance bundle.
Full details: [core-03-reviewer-bundle.md](core-03-reviewer-bundle.md)

**Project tag**: `[claude-multi-ai][AUTO-M1-CORE-03]`

---

## Required Artifacts (5)

| ID | What | Source | Quick check |
|----|------|--------|------------|
| C03-01 | Claim response JSON | `claim_next_task()` | Has `lease` object with 7 fields |
| C03-02 | Task list with lease | `list_tasks(in_progress)` | At least 1 task shows lease |
| C03-03 | Audit log entry | `list_audit_logs()` | `task.claimed` with matching task_id |
| C03-04 | Field verification | Manual table | All 7 fields matched |
| C03-05 | Test results | `test_lease_schema_test_plan.py` | T1, T2, T6, T7 all pass |

## 7 Required Lease Fields

`lease_id` | `task_id` | `owner_instance_id` | `claimed_at` | `expires_at` | `renewed_at` | `attempt_index`

## Pass/Fail Checks

- [ ] All 5 artifacts present and non-empty
- [ ] `lease_id` non-empty and unique per claim
- [ ] `expires_at` = `claimed_at` + configured TTL
- [ ] `owner_instance_id` matches claimer's instance
- [ ] `attempt_index` starts at 1
- [ ] T7 (concurrent claim) shows atomic behavior
- [ ] Cross-source reconciliation: no contradictions
- [ ] Witness observations: all Match? columns filled

## Reject If

1. Any artifact missing without justification
2. Test failures in T1, T2, T6, or T7
3. Unresolved cross-source contradictions
4. Lease field verification has unmatched fields
5. Witness observations unsigned/undated

## Common Mistakes

| Mistake | How to spot | Fix |
|---------|------------|-----|
| Wrong session_id in evidence | session_id differs across C03-01/02/03 | Re-collect from same session |
| `expires_at` wrong | Doesn't equal `claimed_at + TTL` | Check TTL config value |
| Missing `owner_instance_id` | Field is null or empty | Verify agent registered with instance_id |
| Stale evidence | Timestamps from different days | Re-run in single session |
| Placeholder text left in | `PASTE_HERE` or `___` in bundle | Fill all slots before setting READY |

## Verdict

**PASS**: All checks green, no rejections triggered
**REQUEST CHANGES**: Minor issues fixable by preparer
**REJECT**: Test failures or fundamental evidence gaps
