# GOLDM_REVISED 0.6.0 — USD 100, Nov 2025–15 Feb 2026

## Scope

- Broker data: local MT5 `GOLD.i#`
- Period: 2025-11-01 through 2026-02-15
- Starting balance: USD 100
- Signal engine: frozen REVISED 0.6 BUY generator
- Scenario A: 0.20 lot, normal engine stop
- Scenario B: 0.02 lot, normal engine stop
- Scenario C: 0.02 lot, execution stop distance widened to 2×

The 2× stop scenario replays every M1 candle. Signals that arrive while a
wider-stop position is still open are skipped; outcomes are not relabelled
after the fact.

## Signal replay

Normal stops produced 87 signals: 33 targets, 52 stops, two ambiguous same-bar
outcomes, total `+10.012716R`.

The 2× execution stop produced 84 non-overlapping trades: 51 targets, 33
stops, no ambiguous same-bar outcomes, and three skipped overlapping signals.
Because the stop distance doubles while target price stays fixed, its total is
`+17.495445R` under the widened-risk denominator.

## Cash result

| Metric | 0.20 normal | 0.02 normal | 0.02 stop 2× |
|---|---:|---:|---:|
| Completed trades | 1 / 87 | 87 / 87 | 84 / 84 |
| Ending balance | $16.20 | $215.40 | $357.78 |
| Net profit | -$83.80 | +$115.40 | +$257.78 |
| Max drawdown | $83.80 | $58.78 | $77.22 |
| Max drawdown / peak | 83.80% | 43.39% | 54.02% |
| Maximum margin | $81.01 | $10.77 | $10.77 |
| Minimum margin level | below stop-out | 813.74% | 697.06% |
| Profit factor | 0.00 | 1.36 | 1.66 |
| Failure | stop-out | none | none |

The 0.20 scenario completes its first trade at a loss, leaving $83.80. The
next trade, opened 2025-11-10 03:35 server time, reaches adverse equity below
the broker's 20% stop-out threshold. The simulated residual balance is $16.20.

## Verdict

For this period, 0.02 lot with a 2× stop performs better than the normal stop,
but maximum drawdown also rises materially. It is an execution overlay for
research, not a new engine default and not proof that widening stops will
generalize beyond this date range.

Calculations use MT5 broker margin/profit functions. Commission, swap,
slippage, and replay-OHLC versus executable bid/ask differences are not
included. No order was sent.
