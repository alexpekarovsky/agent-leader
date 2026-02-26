# Supervisor Restart & Backoff Tuning

Recommended settings for `--max-restarts`, `--backoff-base`, and
`--backoff-max` depending on whether you are running fast local tests
or longer unattended sessions.

> **Note:** Auto-restart is reserved for future implementation
> (AUTO-M1-CORE-03).  The flags are accepted today but do not trigger
> automatic process restarts.  This guide documents the intended
> behavior so operators can pre-configure values ahead of the feature
> landing.

## Parameter reference

| Flag | Default | Unit | Description |
|------|---------|------|-------------|
| `--max-restarts` | `5` | count | Max consecutive restarts before the supervisor gives up on a process |
| `--backoff-base` | `10` | seconds | Initial delay before the first restart attempt |
| `--backoff-max` | `120` | seconds | Upper bound on exponential backoff delay |
| `--manager-interval` | `20` | seconds | Pause between manager loop iterations |
| `--worker-interval` | `25` | seconds | Pause between worker loop iterations |
| `--manager-cli-timeout` | `300` | seconds | CLI timeout per manager invocation |
| `--worker-cli-timeout` | `600` | seconds | CLI timeout per worker invocation |

## Profiles

### Fast local testing

Use tight intervals and low backoff to iterate quickly during
development or milestone smoke tests.  Crashes surface immediately
rather than being hidden behind long delays.

```bash
supervisor.sh start \
  --max-restarts 2 \
  --backoff-base 3 \
  --backoff-max 10 \
  --manager-interval 10 \
  --worker-interval 10 \
  --manager-cli-timeout 120 \
  --worker-cli-timeout 120
```

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--max-restarts` | `2` | Fail fast — two crashes likely means a real bug |
| `--backoff-base` | `3` | Short initial wait so restarts happen quickly |
| `--backoff-max` | `10` | Cap the delay so you are not waiting during testing |
| `--manager-interval` | `10` | Faster polling catches task state changes sooner |
| `--worker-interval` | `10` | Workers pick up tasks more quickly |
| CLI timeouts | `120` | Prevent a single stuck invocation from blocking the loop for 5+ min |

**Tradeoffs:** Higher API cost from tighter intervals.  Low restart
budget means the system gives up faster on transient failures.  Only
use this profile when you are actively monitoring.

### Unattended / overnight runs

Use the defaults or slightly relaxed values.  The supervisor should
absorb occasional transient failures (network timeouts, rate limits)
without exhausting its restart budget.

```bash
supervisor.sh start \
  --max-restarts 8 \
  --backoff-base 15 \
  --backoff-max 300 \
  --manager-interval 20 \
  --worker-interval 25 \
  --manager-cli-timeout 300 \
  --worker-cli-timeout 600
```

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `--max-restarts` | `8` | Tolerate several transient failures before giving up |
| `--backoff-base` | `15` | Give the API time to recover between attempts |
| `--backoff-max` | `300` | 5 minute cap avoids excessively long delays |
| Intervals | defaults | Standard pacing avoids rate-limit pressure |
| CLI timeouts | defaults | Workers may process large tasks; give them room |

**Tradeoffs:** Slower to surface persistent bugs.  Uses restart
budget more conservatively, which is appropriate when no one is
watching.

## Backoff calculation

When auto-restart ships, the delay before restart attempt _n_ will be:

```
delay = min(backoff_max, backoff_base * 2^(n-1))
```

With the fast-test profile (`base=3, max=10`):

| Attempt | Delay |
|---------|-------|
| 1 | 3s |
| 2 | 6s |
| 3+ | 10s (capped) |

With the unattended profile (`base=15, max=300`):

| Attempt | Delay |
|---------|-------|
| 1 | 15s |
| 2 | 30s |
| 3 | 60s |
| 4 | 120s |
| 5+ | 300s (capped) |

## Checking current restart state

```bash
# View restart counts for all processes
supervisor.sh status

# Inspect a specific restart counter file
cat .autopilot-pids/claude.restarts
```

After the auto-restart feature lands, the `.restarts` files will
reflect actual restart counts.  Currently they remain at `0`.

## References

- [supervisor-cli-spec.md](supervisor-cli-spec.md) — Full flag reference and command semantics
- [supervisor-test-plan.md](supervisor-test-plan.md) — Failure injection and crash recovery tests
- [supervisor-known-limitations.md](supervisor-known-limitations.md) — Auto-restart limitation (CORE-03)
- [headless-mvp-architecture.md](headless-mvp-architecture.md) — Architecture overview
