# CLAUDE.md

Project operating instructions for AI coding agents working on this repository.

## 1) Project context

- Project: OKX futures trading bot (scalping + adaptive logic).
- Main risk: losses from stale price flow, desynced position state, and conflicting exit paths.
- Priority order for all work:
  1. Capital protection and exchange state consistency.
  2. Deterministic entry/exit decisions.
  3. Performance and optimization.

## 2) Non-negotiable invariants

- Single close entrypoint: all position closes must go through orchestrator close pipeline.
- Exit guard first: no close execution before guard checks pass.
- Decision snapshot is single source of truth per decision cycle:
  - `price`, `source`, `age`, `ts`, `position_data`, `side`, `entry_price`.
- No mixed prices in one decision (do not mix ws/mark/rest values without explicit fallback path).
- Position integrity before exit:
  - if `side` invalid or `size <= 0`, resync from exchange before decision.
- Idempotent close behavior:
  - duplicated close attempts for same symbol/reason must be ignored safely.

## 3) Data quality rules

- Entry on stale data is forbidden.
- Non-critical exit on stale data should be blocked or refreshed first.
- Critical exit may use fallback (REST/mark), but must log quality downgrade.
- WebSocket parsing must be safe:
  - empty string / None numeric payloads must not crash loops.

## 4) PnL and risk consistency

- Decision PnL is calculated from normalized tuple:
  - `entry_price + current_price + side + leverage`.
- Exchange upl/margin fields are secondary validation only.
- If model PnL sign conflicts with exchange sign:
  - switch to HOLD, trigger resync, avoid blind emergency close.
- Fee-aware exits:
  - do not close non-critical positions when expected net is near zero or negative after fees.

## 5) Strategy behavior constraints

- BTC/ETH should trade selectively (high-confidence setups only).
- Fast pairs (DOGE/SOL/XRP) may trade more frequently but must respect data quality gates.
- Avoid churn loops:
  - open -> close -> open same side without new confirmation.
- Non-critical exits require confirmation window (multi-tick or time-based), not single noisy tick.

## 6) Required workflow before code changes

1. Discuss scope with user first and confirm understanding.
2. Perform analysis first (logs + code), then provide findings and a fix plan.
3. Wait for explicit user approval before any code edits.
4. Read latest session logs from `logs/futures/archived/...`.
5. Extract concrete failing chains with timestamps and symbols.
6. Map each chain to exact module/path and root cause.
7. Patch smallest safe surface first (P0 stability before tuning) only after approval.
8. Run targeted tests and static checks.
9. Report:
   - what changed,
   - why it fixes root cause,
   - what remains risky,
   - exact files touched.

## 6.1) Mandatory approval gate

- No code changes without explicit user approval.
- No config rewrites, refactors, or file moves without approval.
- If approval is missing or ambiguous: stop at analysis/questions only.
- Approval applies per task scope; if scope changes, request re-approval.

## 6.2) Navigation baseline (must use indexes first)

- Start repository navigation with:
  - `DOCUMENTATION_INDEX.md` for docs map.
  - `TESTS_INDEX.md` for tests map.
- Use indexes before deep filesystem scans to reduce misses and churn.
- If index is outdated, regenerate/update it before broad analysis.

## 7) Testing policy

- Always run focused tests for changed modules first.
- Keep contract tests for WS payload edge cases (empty strings, nulls, missing fields).
- Maintain replay tests on archived bad sessions for regression control.
- Do not claim success without command output.

## 8) Logging and observability

Every fix touching execution flow must preserve/add structured logs for:
- stale ratio,
- fallback usage,
- close pipeline errors,
- pnl mismatch events,
- same-side reentry suppression,
- ws parse errors.

Log messages must be actionable: include symbol, reason, age, source, and decision path.

## 9) Config discipline

- No duplicate YAML keys.
- Keep strict YAML mode enabled in production-like runs.
- Any changed threshold must include rationale and expected impact.

## 10) Git and safety rules

- Never revert unrelated user changes.
- Never use destructive git commands unless explicitly requested.
- Keep commits scoped by root cause/fix group.
- Mention if commit used `--no-verify` and why.

## 11) Security and secrets

- Never print or commit API keys/tokens.
- If a key is exposed in configs/logs, require immediate rotation.

## 12) Response format for analysis tasks

- Findings first (severity order, with file/log references).
- Then root-cause chains.
- Then fix plan by priority (P0/P1/P2).
- Then risk and validation checklist.
- Every key finding must include both:
  - log evidence (file + timestamp/line),
  - code evidence (module/file + function or path).
