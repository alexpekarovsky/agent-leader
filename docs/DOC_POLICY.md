# Documentation Policy — Max-5 Canonical Docs Guardrail

## Canonical Document Set

The repository maintains at most **5 canonical documentation files** (excluding
this policy file itself). All other docs are classified as **transient** and
subject to the cleanup lifecycle below.

### Current Canonical Set

| # | File | Purpose |
|---|------|---------|
| 1 | `README.md` | Project overview, install, quick-start |
| 2 | `CONTRIBUTING.md` | Dev setup, code style, PR process |
| 3 | `ROADMAP.md` | Version milestones and planned features |
| 4 | `RELEASE_NOTES.md` | Per-release changelog |
| 5 | `docs/operator-runbook.md` | Operational procedures for launch / recovery |

### Promotion Rules

A transient doc may be promoted to canonical **only** when:

1. An existing canonical slot is vacated (content merged or retired).
2. The team votes via `orchestrator_decide_architecture` with topic
   `doc-promotion:<filename>`.
3. The total canonical count stays at or below 5 after promotion.

Promotion commits must update the table above and remove the promoted file from
the transient inventory.

## Transient Documentation

Everything in `docs/` that is **not** listed in the canonical table above is
transient. Transient docs are working artifacts — specs, design explorations,
cheat-sheets, and troubleshooting guides generated during development.

### Transient Lifecycle

| Age | Action |
|-----|--------|
| 0–14 days | Active — no action required |
| 15–30 days | Review — author or maintainer decides: merge into canonical, archive, or delete |
| 31+ days | Stale — eligible for automated cleanup; `scripts/doc_guardrail.sh` warns |

### Cleanup Actions

- **Merge**: fold useful content into a canonical doc; delete the transient file.
- **Archive**: move to a `docs/_archive/` directory (git-ignored) for reference.
- **Delete**: remove from the repository entirely.

## Machine-Readable Artifacts Over Docs

Prefer structured, machine-readable artifacts for runtime data:

| Instead of | Use |
|------------|-----|
| Markdown task lists | `state/tasks.json` via orchestrator |
| Prose status reports | `orchestrator_submit_report` with JSON schema |
| Free-form decision notes | `decisions/` ADRs via `orchestrator_decide_architecture` |
| Inline changelogs | `RELEASE_NOTES.md` (canonical) or git log |

## Enforcement

Run the guardrail check:

```bash
./scripts/doc_guardrail.sh
```

This script:
- Counts docs in the canonical set (must be <= 5).
- Lists transient docs with age classification.
- Exits non-zero if canonical count exceeds 5.

Can be added to CI as a soft gate.
