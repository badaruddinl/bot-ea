# Validation Harness Spec

## Purpose

The validation harness should work before MT5 is installed and remain useful after MT5 integration exists.

Its job is to turn trade-level artifacts into comparable summaries, while keeping the project honest about:

- cost realism
- drawdown pressure
- small-sample risk
- portability across hosts

## Minimum artifact inputs

### Trade records

Per trade:

- `symbol`
- `strategy_family`
- `side`
- `entry_time`
- `exit_time`
- `pnl_cash`
- `risk_cash`
- `entry_spread_points`
- `exit_reason`

### Optional metadata

- broker name
- account type
- timeframe
- market regime tag
- backtest mode:
  - `open_prices_only`
  - `every_tick`
  - `real_ticks`

## Minimum summary metrics

- total trades
- win rate
- profit factor
- expectancy in `R`
- total pnl cash
- max drawdown cash
- max drawdown percent
- average holding minutes
- average entry spread

## Required warnings

- sample size still too small
- spread data missing
- no losing trades
- suspiciously optimistic cost assumptions

## Overfitting / realism checks

The harness should not claim robustness from summary returns alone.

At minimum it should support warnings or labels for:

- low trade count
- missing spread/cost data
- results produced by `Open prices only` for intraday breakout logic
- absence of out-of-sample split
- suspicious profit factor with weak cost assumptions

## Cross-host portability

Artifacts should remain readable on another machine without requiring the original terminal.

Recommended outputs:

- markdown summary
- CSV or JSON trade log
- config note describing:
  - broker
  - symbol
  - timeframe
  - test mode
  - parameter profile
- `oos_windows.json`
- `promotion_decision.json`
- `promotion_report.md`

## Promotion artifacts

Promotion decisions should be portable and auditable without the original MT5 terminal.

Minimum files:

- `trade_log.json` or CSV
- `summary.md`
- `oos_windows.json`
- `promotion_decision.json`
- `promotion_report.md`

Promotion artifacts should capture:

- champion label
- challenger label
- thresholds used
- checks run
- pass/fail result
- reasons and warnings
- references to supporting artifacts
