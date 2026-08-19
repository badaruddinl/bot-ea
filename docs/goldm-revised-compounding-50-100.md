# GOLDM_REVISED — compounding from USD 50/100

## Objective

Add an execution-only compounding layer without modifying the frozen signal
generator, production baseline, or `goldm_bear`. Position size is recomputed
from current equity, stop distance, exact MT5 one-lot loss, broker volume step,
margin cap, and drawdown state.

## Implemented controls

- risk sizing is floored to the broker's `0.01` volume step;
- a trade is skipped when its risk budget cannot fund `0.01` lot;
- optional minimum-lot bridge is allowed only under an explicit actual-risk cap;
- risk is reduced at 10% and 15% drawdown;
- new entries pause at 25% drawdown;
- maximum projected margin is 20% of equity;
- scaled targets can be required to have at least 1R room and remain before the
  first obstacle;
- every decision records projected loss, actual projected risk, volume, and
  drawdown state.

The compounding simulator calls MT5 `order_calc_profit` and
`order_calc_margin`; it never sends an order.

## Obstacle-safe 2.5× target result

| Window | Stop 1.75× / target 2.5× | Stop 2× / target 2.5× |
|---|---:|---:|
| Jan 2025–now | 0 trades | 0 trades |
| Nov 2025–15 Feb 2026 | 0 trades | 0 trades |
| Jun 2026–now | 0 trades | 0 trades |
| Full suite 2020–now | 1 trade, +1.07R | 0 trades |

The previous profitability came from allowing the 2.5× runner to cross the
first resistance/psychological/supply obstacle. Once the agreed structural
gate is enforced, a universal 2.5× target is not a viable strategy. It would
need a new causal post-obstacle acceptance algorithm before it could be tested
as a runner again.

## Structural baseline eligibility

The original engine target is already buffered before its first obstacle. The
compounding research additionally rejects invalid BUY targets and targets
below 1R.

| Window | Source outcomes | Eligible structural outcomes |
|---|---:|---:|
| Jan 2025–now | 412 | 388 |
| Nov 2025–15 Feb 2026 | 87 | 82 |
| Jun 2026–now | 20 | 19 |
| Full suite | 1,434 | 1,294 |

## Strict compounding sweep

Risk targets of 1%, 2%, 3%, and 5% were tested from both USD 50 and USD 100.
No strict configuration is positive and free of the hard-drawdown pause across
all three segmented windows and the full suite.

Representative results:

| Start | Risk target | Full suite | Jan 2025–now | Nov–Feb | Jun–now |
|---:|---:|---:|---:|---:|---:|
| $50 | 1% | $50.43 | $48.91 | $49.30 | $49.66 |
| $50 | 2% | $66.71, paused | $42.80 | $47.64 | $48.72 |
| $100 | 1% | $114.45 | $88.73 | $96.94 | $98.72 |
| $100 | 2% | $120.92, paused | $80.72 | $103.11 | $119.61 |
| $100 | 3% | $208.79, paused | $74.20, paused | $97.82 | $116.11 |

At low risk, the `0.01` minimum causes most trades to be skipped. At higher
risk, the early losing sequence reaches the 25% drawdown pause. The selected
tight-stop subset is negative in the January-starting window.

## Minimum-lot bridge sweep

A 2% base risk with minimum-lot actual-risk caps of 5%, 10%, 15%, and 20% was
also tested. Raising the cap does not create a robust result. Representative
5% cap results:

| Start | Full suite | Jan 2025–now | Nov–Feb | Jun–now |
|---:|---:|---:|---:|---:|
| $50 | $60.84, paused | $36.83, paused | $45.88 | $62.39 |
| $100 | $269.71, paused | $73.74, paused | $146.53 | $133.85 |

Caps above 5% still pause or lose in the January window. They merely permit
larger deviations from the configured risk target and are therefore rejected.

## Broker granularity finding

At `0.01` lot, GOLD loses approximately USD 1 for each USD 1 adverse price
move. Median adjusted stops are roughly USD 3–5, so the minimum executable
trade already risks about 3–10% of a USD 50/100 account. A genuine 1–2%
compounding policy requires either:

- a symbol/account with minimum and step `0.001` lot; or
- materially higher starting equity (roughly USD 250–500 to cover typical
  stop distances at 2% risk, before additional safety margin).

## Decision

The risk-sizing module is retained and tested, but it is not wired into the
shadow runtime because no USD 50/100 configuration passes the segmented-window
checks. The minimum-lot bridge remains opt-in and disabled by default.

The signal engine, production worker, Telegram behavior, and `goldm_bear` are
unchanged. No forward task is registered and no order was sent.
