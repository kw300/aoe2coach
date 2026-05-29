# Contributing to aoe2coach

Thanks for helping out! This project turns AoE2 DE replays into AI coaching.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[full,dev,viz,web]"   # full backend + tools (or [fast])
pre-commit install                      # gitleaks + ruff on commit
```

Pick **one** parser backend — `mgz` (`[full]`) and `mgz-fast` (`[fast]`) share the
`mgz` import name and can't coexist. See [CLAUDE.md](CLAUDE.md) for the architecture.

## Before opening a PR

```bash
ruff check src tests && ruff format src tests
pytest
```

- Keep deterministic logic (timings, counts, battle detection) in `metrics.py` — the model
  coaches on numbers, it doesn't compute them.
- Never commit real replays (they hold player PII) or secrets. The pre-commit hooks
  guard both; `.gitignore` blocks `*.aoe2record` except the test fixtures path.
- Add a test for new metrics/aggregation logic. Prefer synthetic objects over committed
  binaries; the integration tests download a fixture on demand.

## Good first issues

- Reconstruct an approximate **villager-count-over-time** curve from the command stream.
- Add **build-order templates** to compare against (a "you opened X, meta is Y" check).
- Expand `civdata`/`benchmarks` coverage; the bundled data refreshes via
  `aoe2coach update-data`.

## Code of conduct

Be kind. Assume good faith. This is a hobby project for a game we love.
