# Tests

This directory contains automated and manual checks for the project.

## Layout

- `tests/unit/` - isolated unit tests.
- `tests/integration/` - integration tests across modules and external APIs.
- `tests/futures/` - futures strategy specific tests.
- `tests/main/` - main scenario tests and orchestrated flows.
- `tests/smoke/` - fast smoke checks and root-level quick tests moved here.
- `tests/check/` - operational checks and exchange diagnostics.
- `tests/debug/` - debugging and analysis scripts.
- `tests/emergency/` - emergency operational scripts.
- `tests/backtest/`, `tests/backtesting/` - backtesting helpers.
- `tests/tools/` - test runners and parameter utilities.
- `tests/reports/` - human-readable status reports.
- `tests/artifacts/`, `tests/results/` - generated test artifacts.
- `tests/archive/` - archived or deduplicated legacy files.
- `tests/development/` - testing standards and maintenance docs.

## Entry points

- Full index: `TESTS_INDEX.md` (project root).
- Reorg audit: `tests/TESTS_AUDIT_2026-02-21.md`.
- Standards: `tests/development/TESTS_STANDARDS.md`.

## Naming

- Test files: `test_*.py`
- Smoke checks: `smoke_*.py`
- Utility runners: `run_*.py` or `*_tester.py`

## Maintenance

- Keep `tests/` root minimal: only README, package marker, and audit files.
- Move new files into a category folder immediately.
- Archive duplicates into `tests/archive/` instead of deleting without review.
