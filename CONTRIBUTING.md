# Contributing to agent-leader

Thanks for your interest in contributing.

## Getting Started

1. Fork the repo and clone locally
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install pytest
   ```
3. Run tests: `python3 -m pytest -q`
4. Install the MCP server: `./scripts/install_agent_leader_mcp.sh --all`

## Development

### Project Structure

```
orchestrator/          Core engine, bus, policy
orchestrator_mcp_server.py   MCP server entry point
scripts/               Installer, doctor, smoke test
config/                Policy files, schemas
tests/                 Test suite
docs/                  Documentation
```

### Running Tests

```bash
python3 -m pytest -q          # quick
python3 -m pytest -v          # verbose
python3 -m pytest -x          # stop on first failure
```

### Code Style

- Python 3.10+ compatible
- Linted with ruff (`ruff check orchestrator/ orchestrator_mcp_server.py`)
- No external dependencies for the core server

## Submitting Changes

1. Create a feature branch from `main`
2. Make your changes
3. Ensure all tests pass
4. Submit a pull request with a clear description

## Reporting Issues

Open an issue with:
- What you expected
- What happened
- Steps to reproduce
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
