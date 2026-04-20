# MT5 Validation Protocol

## Purpose

This document defines how future EA/bot candidates should be validated before demo and live use.

## Validation order

1. hypothesis freeze
2. development backtest
3. MT5 forward split
4. rolling walk-forward
5. cost stress
6. regime split review
7. final untouched holdout
8. broker-specific demo forward test

## 1. Hypothesis freeze

Before optimization begins, freeze:

- strategy family
- trading session
- symbol universe
- intended stop logic
- intended take-profit logic
- core metrics

Do not change these just because early results look weak.

## 2. Development backtest

Minimum requirements:

- use the target broker or closest equivalent symbol specs
- include realistic commission if applicable
- include realistic spread assumptions
- if the strategy is intrabar-sensitive, use `Every tick based on real ticks`

Fail if:

- results depend on unrealistic cost assumptions
- trade count is too small to judge behavior
- margin usage is unsafe even in backtest

## 3. MT5 forward split

Use MT5 forward testing as the first anti-overfit gate.

Pass conditions:

- forward period remains positive or acceptable under the chosen objective
- equity curve degradation is explainable, not catastrophic
- trade distribution is still active and not collapsing

Fail if:

- forward performance collapses relative to development
- only one narrow parameter point survives

## 4. Rolling walk-forward

Recommended pattern:

- 24 months in-sample
- 6 months out-of-sample
- roll repeatedly

Evaluate:

- combined out-of-sample behavior
- stability across windows
- whether performance survives different market regimes

Pass conditions:

- multiple windows remain acceptable
- no dependence on one special period

## 5. Cost stress

Run sensitivity tests for:

- spread widening
- commission increase
- execution delay
- slippage allowance increase

Pass conditions:

- strategy remains viable under harsher but plausible conditions

Fail if:

- small friction changes destroy the edge

## 6. Regime split review

Check performance in:

- trending periods
- choppy/mean-reverting periods
- high volatility periods
- news-heavy periods

Goal:

- understand where the strategy works and where it should stand down

## 7. Final untouched holdout

Keep one final holdout period unseen during tuning.

Rule:

- once viewed for final evaluation, it is no longer a clean holdout

## 8. Demo forward test

Required before live:

- target broker
- target symbol names/specifications
- real session behavior
- real spread behavior
- real order rejection behavior

Log at minimum:

- entry decision
- spread
- stop distance
- lot size
- margin check result
- order result retcode
- partial fill or rejection details

## Pass/Fail checklist

### Backtest

- pass if costs are realistic and results are stable
- fail if edge disappears under plausible costs

### Forward split

- pass if forward remains acceptable
- fail if results collapse after optimization

### Walk-forward

- pass if several OOS windows survive
- fail if only one window carries performance

### Cost stress

- pass if degradation is tolerable
- fail if small cost changes destroy strategy

### Demo

- pass if execution behavior matches assumptions well enough
- fail if slippage, rejections, or spread behavior invalidate the model
