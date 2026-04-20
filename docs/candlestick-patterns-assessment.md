# Candlestick Patterns Assessment

## Bottom line

Candlestick patterns are `not recommended` as the primary signal engine for this project.

They are `conditionally useful` as:

- bar-structure confirmation
- failed-breakout context
- contraction context
- structure-based stop/invalidation aid

For MT5 specifically, they are most defensible when implemented as `closed-bar logic`, not as discretionary live-candle interpretation.

## Why they are not a good primary foundation

### 1. Research is mixed to weak

- some technical-pattern studies find statistical regularities
- other studies find weak or no economic profitability after realistic evaluation
- pattern-only models often struggle to add much predictive value
- intraday futures evidence is especially cold once realistic costs are considered
- a few daily-equity studies in specific markets show short-horizon effects, but these are not portable enough for a universal MT5 bot

This means they are too fragile to be the main v1 edge.

## 2. Overfitting risk is high

If you test:

- dozens of patterns
- many lookbacks
- many markets
- many filters

then false discovery risk rises sharply.

## 3. Execution costs matter more than pattern names

Short-horizon pattern edges are especially vulnerable to:

- spread
- slippage
- delay
- session liquidity changes

## What is still worth using

### Good uses

- `inside bar cluster` for compression
- `breakout close outside range` for confirmation
- `close back inside range after sweep` for failed breakout logic
- `bar high/low` for stop placement
- `body fraction / wick fraction` as a breakout quality filter
- `closed-bar rejection` after a sweep, not a forming-bar guess
- `doji-like indecision` as an exhaustion warning, not a standalone reversal order
- `engulfing/outside-bar style structure` as a short-horizon reversal filter, not a universal entry engine

### Bad uses

- hammer alone means buy
- engulfing alone means reversal
- doji alone means indecision trade
- long catalog of named patterns as standalone entries

## Project rule

For this project:

- candlestick logic may be used as `secondary filter`
- it should be encoded as objective OHLC relationships
- it should not create a large extra parameter surface

## Practical implementation advice

Prefer rules like:

- `close > range_high + buffer`
- `close back inside range after breakout attempt`
- `inside-bar count >= N`
- `body_fraction >= threshold`
- `evaluate on new bar using shift 1+`

Instead of:

- `bullish engulfing`
- `hammer`
- `morning star`

unless the named pattern is reduced to exact OHLC rules and shown to help out-of-sample.

## Pattern-specific stance

- `engulfing / outside-bar body logic`: the strongest candidate for a secondary reversal filter, but still not enough as a universal primary signal
- `inside bar`: more useful as contraction structure than as directional alpha
- `hammer / pin bar`: better treated as a rejection feature than a buy-or-sell command
- `doji`: better treated as indecision or exhaustion context than as an entry trigger

## MT5 implementation notes

- Treat `shift 0` as the forming candle unless the strategy is explicitly intrabar.
- Use `CopyRates` and `MqlRates[]` when evaluating several candles or fields together.
- Do not trust `Open prices only` to validate candle logic that depends on intrabar breakout or rejection behavior.
- Prefer final validation in `Every tick` or `real ticks` for scalping and breakout-sensitive behavior.
