# Progress Summary

Date: 2026-04-20

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

## Key decisions already made

- target platform should be `MT5`
- prefer `research-first`, then `backtest`, then `demo`, then `live`
- lot sizing should be derived from `equity + stop distance + symbol properties`
- margin validation must be done before every order
- strict mode is mandatory when equity is too small for the requested instrument

## Immediate next step

Turn the integrated runtime into a feedback-driven live-validation loop:

1. bridge runtime telemetry into `TradeRecord` and execution-quality validation summaries
2. capture close/modify lifecycle, including realized commission, swap, and exit pnl
3. add broker-aware execution drift monitoring and optional auto-halt thresholds
4. expand GUI from text panel into structured health, reject, and ledger widgets
5. add validation artifact writers for live/demo runs
6. continue broker-specific tuning with fresh out-of-sample slices
7. add strategy-level decision evaluation on top of the now-live execution substrate

## What another host needs to resume

- this repository
- MT5 terminal installed
- target broker credentials
- optional Python runtime for hybrid mode
- a working Python runtime if continuing the scaffold locally
- runtime database and exported validation artifacts if reviewing execution quality on another host
