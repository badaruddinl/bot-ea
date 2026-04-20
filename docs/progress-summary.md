# Progress Summary

Date: 2026-04-20

## Project status

Phase: `research, architecture, and initial scaffold`

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

## Key decisions already made

- target platform should be `MT5`
- prefer `research-first`, then `backtest`, then `demo`, then `live`
- lot sizing should be derived from `equity + stop distance + symbol properties`
- margin validation must be done before every order
- strict mode is mandatory when equity is too small for the requested instrument

## Immediate next step

Turn the scaffold into MT5-aware integration modules:

1. real MT5-backed symbol/account introspection module
2. MT5 adapter for margin/check/session snapshots
3. execution module
4. broker-aware session/news state loading
5. connect polling runtime to real Codex runtime / codex-cli
6. artifact writers for validation runs
7. optional bar-structure confirmation layer

## What another host needs to resume

- this repository
- MT5 terminal installed
- target broker credentials
- optional Python runtime for hybrid mode
- a working Python runtime if continuing the scaffold locally
