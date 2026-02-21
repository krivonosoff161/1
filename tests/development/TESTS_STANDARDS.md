# Tests standards

## Purpose
- Keep test suite maintainable, discoverable, and safe to run.

## Directory rules
- `tests/unit/` for isolated unit tests.
- `tests/integration/` for cross-module and external dependency tests.
- `tests/futures/` for futures strategy tests.
- `tests/smoke/` for quick checks from root-level scripts.
- `tests/tools/` for helper scripts and runners, not assertions.
- `tests/reports/` for markdown status reports.
- `tests/artifacts/` and `tests/results/` for json/txt outputs.
- `tests/archive/` for historical/duplicated material.

## Naming
- Tests: `test_*.py`.
- Utility scripts: `*_tester.py` or `run_*.py`.
- Reports: `YYYY-MM-DD_<topic>.md` when possible.

## Runtime safety
- Test scripts that can place/cancel orders must be in `integration`, `debug`, or `emergency`.
- Mark potentially destructive tests clearly in docstrings and README.

## Maintenance
- Keep root `tests/` clean (entrypoints only).
- Run dedupe/audit scripts after major changes.
- Archive, do not hard-delete, ambiguous duplicates.
