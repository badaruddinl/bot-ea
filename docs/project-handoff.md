# Project Handoff

## What this project is

This project is the research and design foundation for an `autonomous MT5 trading bot / EA` that can:

- adapt decisions to `equity`, `margin`, and `symbol properties`
- decide whether a requested market is reasonable for the current account
- warn the user when the requested symbol is too risky
- still operate under `strict mode` if the user insists
- support future implementation as:
  - `native MQL5 EA`
  - `hybrid MQL5 + Python`

This is intentionally a `research-first` repository. It is not yet the execution bot itself.
It now also contains the first `testable scaffold` for the risk-first core.

## Why the project exists

The goal is to avoid building the EA from zero or from generic internet snippets.

Instead, the project already captures:

- official MT5 platform capabilities
- risk engine design rules
- strategy-family recommendations that are realistic to automate
- parameter boundaries that can be tuned later with broker-specific data
- portability notes so the work can continue on another machine

## Current state

The repository currently contains:

- `README.md`
  - high-level project purpose and structure
- `research/2026-04-20-market-and-platform-research.md`
  - consolidated research on MT5 APIs, risk concepts, slippage, session behavior, and baseline design choices
- `research/2026-04-20-stage-2-deep-research.md`
  - deeper research on execution variance, validation robustness, parameter governance, and strategy-family prioritization
- `research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md`
  - deeper research on practical decision trees, pseudo-rules, and whether candlestick patterns should be used
- `research/2026-04-20-stage-4-implementation-and-live-research-notes.md`
  - latest implementation-focused research on MT5 capabilities, server-time handling, and live execution constraints
- `docs/ea-bot-blueprint.md`
  - target architecture and subsystem design
- `docs/mt5-validation-protocol.md`
  - concrete validation order for backtest, forward, walk-forward, cost stress, and demo
- `docs/strategy-candidates.md`
  - practical candidate strategy families with guardrails and priority order
- `docs/decision-tree-pseudorules.md`
  - practical strategy decision flow for the future bot
- `docs/candlestick-patterns-assessment.md`
  - explicit assessment of candlestick patterns as primary vs secondary signal logic
- `docs/risk-engine-spec.md`
  - implementation contract for operating mode, sizing, and guardrails
- `config/parameter-map.md`
  - separation between user parameters, MT5-derived parameters, and tuned parameters
- `data/README.md`
  - placeholder for future backtest/demo artifacts
- `src/bot_ea/`
  - first Python scaffold for risk logic, MT5 snapshot builders, execution guards, decision-family selection, and MT5 adapter seams
- `tests/test_risk_engine.py`
  - starter tests for the risk-engine slice

## Progress summary

### Finished

- Project folder created at `D:\luthfi\project\bot-ea`
- Research collected from official MetaTrader documentation
- Additional external references gathered for:
  - position sizing
  - margin discipline
  - slippage and stop behavior
  - session liquidity for short-term trading
- Risk engine baseline defined
- Equity-aware strict-mode concept defined
- Portability docs started
- Python core scaffold added
- Risk engine spec added
- Initial risk-engine tests added

### Resolved design direction

- Prefer `MT5` over `MT4`
- Keep `risk engine` as the first subsystem to implement
- Prefer `single-symbol` and `single-strategy-family` in v1
- Use `research` for priors and `backtests/demo forward tests` for actual tuning

### Not built yet

- no live EA code
- no MT5 terminal integration yet
- no MQL5 execution code yet
- no backtest harness yet
- no broker-specific symbol profiles yet
- no strategy module beyond scaffold placeholders

## How to continue on another host

### 1. Minimum host requirements

- Windows host or VPS with `MetaTrader 5`
- broker/demo account configured in MT5
- Git
- Python 3 if hybrid path will be used

### 2. First files to read

Read in this order:

1. `README.md`
2. `research/2026-04-20-market-and-platform-research.md`
3. `research/2026-04-20-stage-2-deep-research.md`
4. `research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md`
5. `research/2026-04-20-stage-4-implementation-and-live-research-notes.md`
6. `docs/ea-bot-blueprint.md`
7. `docs/mt5-validation-protocol.md`
8. `docs/strategy-candidates.md`
9. `docs/decision-tree-pseudorules.md`
10. `docs/candlestick-patterns-assessment.md`
11. `docs/risk-engine-spec.md`
12. `config/parameter-map.md`
13. `src/bot_ea/`

### 3. Recommended next implementation steps

1. Create `src/` skeleton for:
   - account introspection
   - symbol introspection
   - MT5 adapter
   - execution engine
2. Decide implementation path:
   - `MQL5 native only`
   - `MQL5 + Python hybrid`
3. Start with one symbol and one strategy family
4. Add logging before adding complex strategy logic
5. Build backtest and demo-test loop before any live deployment

### 4. Suggested module order

- `risk_engine`
- `mt5_adapter`
- `market_filters`
- `execution_engine`
- `position_manager`
- `strategy_baseline`
- `telemetry`

### 5. Suggested first deliverables

- `docs/risk-engine-spec.md`
- complete `src/bot_ea/` adapter and account/symbol snapshot modules
- backtest configuration template
- broker symbol profile notes

## Research assumptions to keep in mind

- Many internet trading ideas do not transfer across brokers
- Spread, slippage, stop levels, contract size, and filling modes can vary per symbol
- Small equity changes what is viable
- A symbol can be valid in theory but still unsuitable for a particular account

## Practical continuation checklist

- confirm the target broker and account type
- export the available symbol list from MT5
- inspect contract size, min lot, lot step, stops level, and spread
- choose the first market:
  - likely `EURUSD`, `GBPUSD`, `XAUUSD`, or one index CFD depending on broker
- choose the first strategy family
- implement risk engine before signal logic
- run demo-only until behavior is observable and logged
