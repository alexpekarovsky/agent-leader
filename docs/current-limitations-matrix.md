# Current Limitations Matrix

This matrix tracks current operational limits against the roadmap phases.

| Area | Current Limitation | Target Phase | Notes |
|---|---|---|---|
| Task ownership | Claims are mostly agent-level, not always `instance_id`-strict in operator workflows | Phase B | Align all operator docs and tooling to instance-scoped ownership. |
| Recovery | Lease-first recovery is documented but still operator-assisted in some paths | Phase C | Expand lease automation and tighter expiry handling. |
| Dispatch | Deterministic dispatch path still has partial manual fallback in some headless checks | Phase D | Standardize `dispatch.command`/`dispatch.ack`/`dispatch.noop` handling. |
| Observability | Some health checks are script-based and not yet MCP-first | Phase D | Keep parity between interactive and headless diagnostics. |
| Validation | A few smoke checks are doc-contract heavy and can drift | Phase B | Keep smoke assertions aligned with current topology. |
| Team routing | Team filters work but lane policy UX can still be improved | Phase C | Add clearer team-scoped operator views. |
| Retry model | Retry semantics exist but operators still rely on manual triage in edge cases | Phase C | Expand lease + retry policy defaults. |
| Runbooks | Multiple runbooks exist with overlapping guidance | Phase B | Consolidate around one canonical path per mode. |
| Status surfaces | Status fields are mostly aligned but still evolving | Phase D | Freeze status contract and publish migration notes. |
| Scale behavior | Large fan-out teams need stronger dispatch diagnostics | Phase D | Correlation-driven dispatch telemetry and no-op reason codes. |

## Cross-Check With Roadmap

- `instance_id` maturity maps to Phase B.
- lease reliability and expiry handling map to Phase C.
- dispatch determinism and no-op diagnostics map to Phase D.

Reference: [roadmap.md](roadmap.md)
