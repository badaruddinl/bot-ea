# Progress Summary

Date: 2026-04-21

## Project status

Phase: `live MT5 integration, execution telemetry, and validation hardening`

Research depth: `stage 5`

## Completed work

- created the project workspace
- gathered platform research from official MT5/MQL5 docs
- gathered complementary research on:
  - risk management
  - margin discipline
  - slippage
  - scalping session behavior
- defined:
  - risk engine baseline
  - equity-aware strict mode
  - parameter ownership map
  - architecture blueprint
- deepened:
  - broker execution variance research
  - MT5 validation/anti-overfitting protocol
  - strategy family prioritization
  - parameter governance for low-overfit systems
- added:
  - decision-tree and pseudo-rule guidance
  - candlestick pattern relevance assessment
- created:
  - risk engine specification
  - Python package scaffold in `src/bot_ea`
  - initial unit tests for position sizing and strict-mode behavior
  - MT5 snapshot builders for account and symbol normalization
- added:
  - stage-4 implementation and live research notes
  - MT5 adapter boundary notes
  - session-breakout v1 notes
  - validation harness spec
  - stage-5 subagent integration notes
  - mock MT5 adapter
  - session-breakout strategy scaffold
  - validation summary module
  - allocation guidance notes
  - SQLite runtime store scaffold
  - stop-policy module
  - Codex polling runtime scaffold
- integrated:
  - live MT5 adapter with `symbol_info`, `symbol_select`, `order_check`, and `order_send` support
  - MT5 snapshot provider for live account, symbol, and tick hydration
  - broker preflight and execution runtime with safe default `dry-run`
  - richer execution guard checks around account and broker tradability
  - runtime telemetry for quoted price, executed price, slippage, fill latency, retcode, order ticket, and deal ticket
  - attempt-level execution lifecycle logging with `INTENT`, `PRECHECK`, and `FILL` phases
  - promotion gate artifacts and markdown/json audit export
  - simple live GUI panel for refresh, preflight, execute, and runtime telemetry review
  - allocation mode support for `fixed_cash`, `percent_equity`, and `full_equity` in the GUI
- documented:
  - live MT5 Python integration notes
  - trading foundation and tuning notes
  - promotion artifact expectations in validation harness docs
- added:
  - desktop GUI runtime controls for MT5 readiness, codex-cli readiness, and background polling runtime start/stop
  - coverage-aware execution-quality metrics for runtime telemetry
  - desktop runtime runbook and Windows packaging plan
  - app-managed websocket service flow for the Qt desktop app
  - multi-page Qt workspace with `Dashboard`, `Strategy`, `History`, `Logs`, and `Settings`
  - runtime-fed market snapshot updates in the Qt workspace while runtime is active
  - explicit blocking of manual MT5 actions while runtime owns the MT5 session
  - stricter Codex response-contract handling plus clearer `NO_TRADE` fallback reasons
  - first-pass startup gate in the Qt app that requires `service -> MT5 -> Codex` before unlocking the main workspace

## Key decisions already made

- target platform should be `MT5`
- prefer `research-first`, then `backtest`, then `demo`, then `live`
- lot sizing should be derived from `equity + stop distance + symbol properties`
- margin validation must be done before every order
- strict mode is mandatory when equity is too small for the requested instrument

## Immediate next step

Move from a usable operator console toward the master-brief startup model:

1. expand the startup gate beyond `service -> MT5 -> Codex` into richer dependency probing
2. add explicit `operator` vs `dev/mock` mode behavior
3. continue syncing copy/docs so the Qt app, runbooks, and user manual match exactly
4. continue hardening Codex decision handling and timeout behavior
5. add reconnect/account-change UX on top of the now-stabler runtime/session ownership model

## Desktop runtime note

The Qt desktop app is now the primary operator surface for supervised development and demo tests:

- it can manage the local websocket service from inside the app
- it gates workspace entry behind a first-pass startup dependency check
- it separates runtime work into multiple pages instead of one mixed panel
- it keeps live trading behind explicit operator action and approval

It is still not positioned as unattended live-trading software, and the startup gate is still only a first implementation pass.

## What another host needs to resume

- this repository
- MT5 terminal installed
- target broker credentials
- optional Python runtime for hybrid mode
- a working Python runtime if continuing the scaffold locally
- runtime database and exported validation artifacts if reviewing execution quality on another host
