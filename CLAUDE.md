## GitHub Actions Security (MANDATORY)

**NEVER use tag-based references for GitHub Actions.** Always pin to the full commit SHA.

Bad: `uses: actions/checkout@v4`
Good: `uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5 # v4`

Why: Tags can be force-pushed by attackers (see Trivy supply chain attack, March 2026). SHAs are immutable.

When adding or updating any GitHub Action:
1. Find the SHA: `gh api repos/OWNER/REPO/git/ref/tags/TAG --jq '.object.sha'`
2. Use the SHA in the workflow file
3. Add a `# vX` comment after the SHA for readability

**4-Point CI/CD Security Checklist (enforce on every workflow change):**
1. **No `pull_request_target`** — runs with repo owner permissions, trivially exploitable from forks
2. **Pin all actions to SHA** — tags are mutable, SHAs are not
3. **Explicit `permissions: contents: read`** — without this, GitHub defaults to read+write on everything
4. **Minimal secrets** — never expose secrets to fork PRs, scope to specific jobs

---

## Project Tracking (Lumen)

This project is tracked by Lumen Project Command Center.

- **Project file**: `project.yaml` in repo root
- **Dashboard**: https://127.0.0.1:8888 → Projects tab
- **IMPORTANT**: When you complete a milestone, change its `status` to `done` in `project.yaml`.
  When you start working on one, change it to `in_progress`. Auto-detected on next scan.
- Effort sizes: XS (<1h) | S (1-2h) | M (2-4h) | L (4-8h) | XL (8-16h)
