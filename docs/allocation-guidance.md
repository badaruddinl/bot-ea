# Allocation Guidance

## Purpose

The bot should distinguish between:

- `account equity`
- `allocated capital`
- `practical tradability`

This means a user may allocate only part of the account, but the engine should still warn or reject if the allocation is unrealistic for the chosen symbol and style.

## Current rule in the repo

The current scaffold supports:

- allocation by full equity
- allocation by percent of equity
- allocation by fixed cash

The risk engine then computes:

- `capital_base_cash`
- `risk_cash_budget`
- `recommended_minimum_allocation_cash`

and may reject if:

- allocated capital is too small
- allocated risk cash is too small
- minimum volume cannot be supported for the requested stop distance

## Recommendation layer

The repo now exposes a practical recommendation layer by:

- instrument class
- trading style

Current baseline recommendations in code are intentionally simple and testable.

Examples:

- `forex_major`
  - scalping: about `100`
  - intraday: about `75`
  - swing: about `125`
- `metal`
  - scalping: about `250`
  - intraday: about `150`
  - swing: about `300`
- `index_cfd`
  - scalping: about `300`
  - intraday: about `200`
  - swing: about `350`

These are not broker promises or universal truths. They are practical guardrail defaults for the current scaffold.

## User-facing behavior

The engine can now produce messages like:

- `recommended minimum allocation for XAUUSD intraday is about 150.00`
- `XAUUSD may be impractical with allocated capital 125.00; recommended minimum is about 150.00`
- `allocated risk cash below practical minimum for scalping setup`

## Architecture note

This guidance belongs to code, not only config.

Why:

- the recommendation depends on instrument class
- the warning depends on style
- the final rejection depends on minimum lot, stop distance, and risk cash

So config may tune the profile, but the logic still lives in the risk engine.
