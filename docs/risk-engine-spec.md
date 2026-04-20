# Risk Engine Spec

## Purpose

The risk engine is the first implementation slice because it is the most stable part of the system and the least dependent on broker-specific strategy tuning.

It should answer five questions before any order is sent:

1. Is this symbol reasonable for the current account?
2. Which operating mode applies: `recommend`, `caution`, or `strict`?
3. How much cash risk is still available right now?
4. What is the maximum normalized position size for the proposed stop distance?
5. Should execution be blocked because friction or risk pressure is too high?

## Inputs

### User profile

- `trading_style`
- `risk_profile`
- `market_allowlist`
- `account_mode`
- optional `capital_allocation`
  - `full_equity`
  - `percent_equity`
  - `fixed_cash`
- optional `force_symbol` if the user insists on a risky market

### Account snapshot

- `equity`
- `balance`
- `free_margin`
- `margin_level`
- `current_open_risk_pct`
- `daily_realized_loss_pct`
- `positions_total`

### Symbol snapshot

- `symbol`
- `instrument_class`
- `risk_weight`
- `trade_mode`
- `order_mode`
- `execution_mode`
- `filling_mode`
- `point`
- `tick_size`
- `tick_value`
- `volume_min`
- `volume_max`
- `volume_step`
- `spread_points`
- `stops_level_points`
- `freeze_level_points`
- `quote_session_active`
- `trade_session_active`
- optional `volatility_points`

Session and calendar timestamps should be normalized to `TimeTradeServer`, not local host time.

## Outputs

### Suitability assessment

- `operating_mode`
- `reasons`
- `warnings`

### Position sizing result

- `capital_base_cash`
- `effective_risk_pct`
- `risk_cash_budget`
- `normalized_volume`
- `estimated_loss_cash`
- `stop_distance_points`
- `accepted`
- `rejection_reason`

### Execution guard result

- pass/fail gates
- gate details

## Core rules

### 1. Operating mode classification

`Recommend`

- symbol is tradable now
- spread is efficient relative to volatility
- free margin buffer is healthy
- daily loss and open-risk pressure are low

`Caution`

- symbol is tradable but one or more pressure indicators are elevated
- example: spread is borderline, free margin is getting tight, or equity is small for the symbol risk weight

`Strict`

- user forces a risky symbol
- or friction/risk pressure is high enough that baseline behavior is no longer acceptable

### 2. Effective risk budget

Before risk is calculated, the engine must determine the `capital base`.

This can be:

- full account equity
- a percentage of equity
- a fixed cash allocation capped by current equity

All percentage-based risk calculations should then use `capital_base_cash`, not always full account equity.

The engine should start from a base policy risk percentage and scale it by mode:

- `recommend`: `1.00 x`
- `caution`: `0.75 x`
- `strict`: `0.50 x`

The resulting cash budget must then be capped by:

- remaining daily loss capacity
- remaining open-risk capacity

## Allocation realism

Allocated capital is allowed, but the engine should reject unrealistic cases.

Examples:

- account equity is `1000`, but user allocates only `10`
- user then asks for `1%` risk per trade
- resulting risk cash is only `0.10`

That may be mathematically valid, but it is not practically tradable for many symbols once minimum lot and stop-distance reality are applied.

So the engine should reject when:

- allocated capital is below a practical minimum
- effective risk cash is below a practical minimum
- the resulting risk cash cannot support even the minimum symbol volume for the requested stop distance

## Position sizing formula

Definitions:

- `stop_distance_price = stop_distance_points * point`
- `adverse_ticks = stop_distance_price / tick_size`
- `loss_per_lot = adverse_ticks * tick_value`
- `raw_volume = risk_cash_budget / loss_per_lot`

Then normalize down to broker constraints:

- clamp to `volume_min <= volume <= volume_max`
- round down to `volume_step`

If normalized volume falls below `volume_min`, the trade should be rejected instead of silently oversizing.
The rejection should explicitly tell the user that the allocated capital is too small for the chosen symbol/stop configuration.

## Guardrails

The risk engine should reject or escalate when:

- `trade_session_active` is false
- `quote_session_active` is false
- `spread_points / volatility_points` exceeds the allowed threshold
- `daily_realized_loss_pct` is at or above the daily limit
- `current_open_risk_pct` is at or above the open-risk limit
- stop distance is smaller than `stops_level_points`
- free margin buffer is too small

## Important design constraints

- Treat this as deterministic business logic, not strategy alpha.
- Keep the parameter surface small.
- Avoid symbol-specific tuning in the engine itself.
- Leave actual margin estimation to the MT5 adapter when possible.
- Prefer pure functions and testable dataclasses over terminal-coupled logic.
- Refresh execution-sensitive fields close to send time:
  - spread
  - stops level
  - freeze level
  - trade mode / order mode
- Keep a `symbol capability snapshot` separate from strategy state so the execution engine can revalidate immediately before order submission.

## Planned integration points

### MT5 adapter

Will later provide:

- account snapshot loading
- symbol snapshot loading
- `OrderCalcMargin`
- `OrderCalcProfit`
- `OrderCheck`
- trade and quote session maps per symbol
- calendar cache support for tester/backtest use

### Decision engine

Will later request:

- operating mode
- effective risk budget
- normalized size
- gate failures or warnings

## Minimum acceptance tests

The first scaffold should verify:

1. strict mode reduces risk versus recommend mode
2. volume normalization rounds down correctly
3. daily loss exhaustion blocks new trades
4. open-risk exhaustion blocks new trades
5. tiny stop distances respect stop-level constraints
