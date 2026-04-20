# Decision Tree and Pseudo-Rules

## Purpose

This document turns the strategy-family research into a practical decision flow for a future MT5 bot.

## Global top-level gate

The bot should not even evaluate strategy signals unless all of these pass:

1. terminal connected
2. account trading allowed
3. symbol selected and synchronized
4. symbol trade mode allows the intended direction
5. latest tick is fresh
6. spread is within allowed absolute and relative thresholds
7. no high-impact blackout event is active
8. daily loss limit not hit
9. margin headroom sufficient
10. no cooldown lock active

Implementation note:

- session gating should be `symbol-aware` through MT5 quote/trade session data, not only fixed local clock windows
- strategy logic should default to `closed-bar evaluation` unless a specific family is intentionally designed for intrabar behavior

## Family selection layer

Evaluate in this order:

1. `Session Breakout`
2. `Pullback Continuation`
3. `Volatility Contraction -> Expansion`
4. `Failed Breakout / Range Reversion`

The first family that passes all its own gates wins. Do not stack multiple families on the same bar unless explicitly designed later.

## 1. Session Breakout

### Preconditions

- current time is in allowed session window
- quote session active and trade session active for the symbol
- session is historically active for the symbol
- opening range exists
- opening range width is not too narrow and not too wide relative to ATR
- spread is normal
- no event embargo active around scheduled macro news

### Trigger logic

- price breaks above or below the defined opening/session range
- breakout exceeds a minimum ATR-normalized buffer
- breakout bar quality is acceptable

### Confirmation ideas

- breakout bar closes outside the range
- body fraction is strong enough
- no immediate rejection back into the range

### Stand down if

- high-impact news blackout is active
- two false breaks already happened this session
- spread widened abnormally
- opening range already got distorted by pre-session drift

## 2. Pullback Continuation

### Preconditions

- a directional impulse already occurred
- trend filter agrees with direction
- volatility is active but not chaotic
- market is not in obvious chop
- pullback occurs in a liquid trading window with controlled spread

### Trigger logic

- price pulls back to an objective structure area
- pullback depth stays within allowed bounds
- price resumes in trend direction

### Confirmation ideas

- continuation close beyond a trigger level
- pullback does not break trend structure
- no-chase distance from anchor move is respected

### Stand down if

- midday chop dominates
- pullback is too deep
- impulse was only one news spike with no structure
- price is already too extended from the trend anchor

## 3. Volatility Contraction -> Expansion

### Preconditions

- a contraction structure is present
- session is active enough to support expansion
- spread is still efficient relative to expected move
- compression is not merely dead-session inactivity

### Trigger logic

- price breaks out of contraction boundary
- expansion follows with sufficient follow-through

### Confirmation ideas

- multiple inside bars or low-range percentile
- ATR regime recovering from compressed state
- breakout close holds outside structure

### Stand down if

- setup appears immediately before major news
- contraction occurs in a dead session
- prior move is already exhausted

## 4. Failed Breakout / Range Reversion

### Preconditions

- trend-day conditions are absent
- a meaningful range or level exists
- symbol liquidity is good enough

### Trigger logic

- price sweeps outside the range/level
- closes back inside
- follow-through failure is visible

### Confirmation ideas

- rejection wick plus close back inside
- no macro catalyst active
- spread remains controlled

### Stand down if

- strong trend-day conditions
- cash open style price discovery
- high-impact news day

## Position sizing layer

For every family:

1. compute stop location
2. compute risk cash from equity and risk budget
3. compute raw lot from stop distance and account-currency risk
4. clamp to broker lot constraints
5. re-check margin and free-margin safety

## Pseudo-rule skeleton

```text
if not global_gate_pass:
    skip

family = choose_family_by_priority()
if family is None:
    skip

setup = evaluate_family(family)
if not setup.valid:
    skip

stop = derive_structure_stop(setup)
target = derive_target(setup)
size  = compute_risk_size(setup, stop)

if not execution_guard_pass(symbol, size, stop, target):
    skip

send_order()
enter_cooldown_if_needed()
```

## Candlestick / bar-structure role

Allowed role:

- only as objective bar-structure confirmation
- preferably using closed bars that have already finished printing

Examples:

- breakout candle closes outside range
- failed breakout closes back inside
- inside-bar cluster defines contraction

Disallowed role for v1:

- large pattern dictionary as the main signal engine
- live-candle pattern interpretation that changes meaning while the bar is still forming
