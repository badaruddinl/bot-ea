# Session Breakout V1

## Intent

This is the first baseline strategy family because it matches the strongest research support:

- session activity matters
- news windows matter
- spread and execution quality matter
- closed-bar breakout confirmation is easier to validate than intrabar discretion

## V1 scope

Use only a narrow, testable setup:

- single symbol
- single timeframe
- closed-bar evaluation
- one opening-range breakout attempt per direction per session

## Required inputs

- closed bars in time order
- session-active flag
- news-blackout flag
- symbol spread
- symbol volatility proxy
- symbol quote/trade session state

## Rule outline

1. Build an opening range from the first `N` closed bars.
2. Reject the setup if the range is too narrow or too wide.
3. Reject the setup if spread is too wide relative to volatility.
4. Reject the setup if quote/trade session is inactive.
5. Reject the setup if a news blackout is active.
6. Accept a long only if the trigger bar closes above the range plus a buffer with enough body quality.
7. Accept a short only if the trigger bar closes below the range minus a buffer with enough body quality.

## Stand-down conditions

- news blackout
- inactive quote/trade session
- opening range distortion
- weak trigger body
- wide spread relative to expected move

## Why this version stays narrow

- easier to test outside MT5
- easier to compare against future MT5-backed replay
- lower risk of accidental overfitting

## Current repo status

Current implementation:

- `src/bot_ea/strategies/session_breakout.py`
- `tests/test_session_breakout.py`
