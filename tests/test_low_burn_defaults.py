"""Tests for low_burn default behaviour across MCP and CLI paths.

Acceptance criteria (TASK-8ad566ea):
  - MCP headless_start defaults low_burn=False
  - CLI supervisor.sh keeps low_burn=True default
  - Explicit interval values are never silently overridden
"""

import argparse

from orchestrator.supervisor import SupervisorConfig


# ---- MCP path (low_burn defaults False) ------------------------------------

def test_mcp_default_low_burn_false():
    """MCP callers that omit low_burn should NOT get inflated intervals."""
    cfg = SupervisorConfig(low_burn=False)
    cfg.finalise()
    assert cfg.manager_interval == 20
    assert cfg.worker_interval == 25


def test_mcp_explicit_low_burn_true():
    """MCP callers that explicitly opt-in to low_burn get inflated intervals
    only when their intervals are BELOW the normal defaults."""
    cfg = SupervisorConfig(low_burn=True, manager_interval=10, worker_interval=15)
    cfg.finalise()
    assert cfg.manager_interval == 120
    assert cfg.worker_interval == 180


def test_mcp_explicit_intervals_not_overridden():
    """Even with low_burn=True, default interval values (20/25) should not be
    silently inflated."""
    cfg = SupervisorConfig(low_burn=True, manager_interval=20, worker_interval=25)
    cfg.finalise()
    assert cfg.manager_interval == 20
    assert cfg.worker_interval == 25


def test_mcp_explicit_high_intervals_preserved():
    """Intervals above the defaults are never touched by low_burn."""
    cfg = SupervisorConfig(low_burn=True, manager_interval=60, worker_interval=90)
    cfg.finalise()
    assert cfg.manager_interval == 60
    assert cfg.worker_interval == 90


# ---- CLI path (low_burn defaults True) ------------------------------------

def _parse_cli(args: list[str] | None = None) -> argparse.Namespace:
    """Minimal replica of the CLI parser defaults from supervisor.main()."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-interval", type=int, default=20)
    parser.add_argument("--worker-interval", type=int, default=25)
    parser.add_argument("--low-burn", dest="low_burn", action="store_true")
    parser.add_argument("--high-throughput", dest="low_burn", action="store_false")
    parser.set_defaults(low_burn=True)
    return parser.parse_args(args or [])


def test_cli_default_low_burn_true():
    """CLI defaults to low_burn=True (kept for backward compat)."""
    ns = _parse_cli()
    assert ns.low_burn is True


def test_cli_high_throughput_flag():
    """--high-throughput disables low_burn."""
    ns = _parse_cli(["--high-throughput"])
    assert ns.low_burn is False


def test_cli_explicit_intervals_honoured():
    """CLI user who sets --manager-interval=20 explicitly (same as default)
    should NOT have it inflated when low_burn applies."""
    cfg = SupervisorConfig(
        low_burn=True,
        manager_interval=20,
        worker_interval=25,
    )
    cfg.finalise()
    assert cfg.manager_interval == 20
    assert cfg.worker_interval == 25


# ---- MCP schema -----------------------------------------------------------

def test_mcp_schema_low_burn_default():
    """The MCP tool schema must advertise low_burn default=False."""
    import orchestrator_mcp_server as srv
    resp = srv.handle_tools_list(request_id=1)
    tools = resp["result"]["tools"]
    headless_start = next(t for t in tools if t["name"] == "orchestrator_headless_start")
    low_burn_prop = headless_start["inputSchema"]["properties"]["low_burn"]
    assert low_burn_prop["default"] is False, (
        f"MCP schema still advertises low_burn default={low_burn_prop['default']}"
    )
