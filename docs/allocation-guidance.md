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

Current baseline recommendations in code are intentionally simple and testable, but they now follow a two-layer evaluation:

1. `rejection`
   Used when allocated capital is not enough for healthy minimum openability.
2. `warning`
   Used when a trade may still open, but the capital is too thin for the requested style.

## Minimum openability

The risk engine now computes:

- `min_open_margin = price * contract_size * min_lot * margin_rate`
- `hard_floor = max(class_hard_floor, 2 * min_open_margin)`

The trade is rejected when:

- `allocation_usd < hard_floor`

This is intentionally stricter than broker minimum margin alone. The extra `1x` margin buffer is there to absorb spread, early floating loss, and avoid razor-thin free margin on small accounts.

## Recommended minimum allocation by style

Examples:

- `forex_major`
  - scalping: about `50`
  - intraday: about `100`
  - swing: about `150`
- `metal`
  - scalping: about `150`
  - intraday: about `250`
  - swing: about `400`
- `index_cfd`
  - scalping: about `100`
  - intraday: about `200`
  - swing: about `350`

These are not broker promises or universal truths. They are practical guardrail defaults for the current scaffold.

## Minimum practical risk by style

The engine also computes a class-aware practical minimum risk floor. Baseline defaults:

- `forex_major`
  - scalping: `1 USD`
  - intraday: `3 USD`
  - swing: `6 USD`
- `metal`
  - scalping: `3 USD`
  - intraday: `10 USD`
  - swing: `20 USD`
- `index_cfd`
  - scalping: `2 USD`
  - intraday: `8 USD`
  - swing: `18 USD`

This is converted to percentage of allocated capital:

- `minimum_practical_risk_pct = minimum_practical_risk_usd / allocation_usd`

Severity rules:

- reject if `minimum_practical_risk_pct > 2 * max_style_risk_pct`
- warn if `minimum_practical_risk_pct > max_style_risk_pct`

Baseline `max_style_risk_pct`:

- `scalping`: `2%`
- `intraday`: `4%`
- `swing`: `5%`

## User-facing behavior

The engine can now produce messages like:

- `XAUUSD masih bisa diperdagangkan dengan alokasi 125.00 USD, tetapi kurang realistis untuk style intraday. Minimum rekomendasi kami 250.00 USD.`
- `Alokasi 40.00 USD ditolak untuk EURUSD. Modal ini belum cukup untuk ukuran posisi minimum yang sehat.`
- `XAUUSD tidak realistis untuk alokasi 25.00 USD.`

## Architecture note

This guidance belongs to code, not only config.

Why:

- the recommendation depends on instrument class
- the warning depends on style
- the final rejection depends on minimum lot, contract size, margin rate, and practical risk percentage

So config may tune the profile, but the logic still lives in the risk engine.
