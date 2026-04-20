# Progress Summary

Date: 2026-04-20

## Project status

Phase: `research and architecture`

Research depth: `stage 2`

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

## Key decisions already made

- target platform should be `MT5`
- prefer `research-first`, then `backtest`, then `demo`, then `live`
- lot sizing should be derived from `equity + stop distance + symbol properties`
- margin validation must be done before every order
- strict mode is mandatory when equity is too small for the requested instrument

## Immediate next step

Turn the blueprint into code scaffolding:

1. risk engine spec
2. symbol/account introspection module
3. execution module
4. one baseline strategy
5. validation harness and test logging

## What another host needs to resume

- this repository
- MT5 terminal installed
- target broker credentials
- optional Python runtime for hybrid mode
