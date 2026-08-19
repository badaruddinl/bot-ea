# GOLDM_REVISED 0.6.0 — USD 100, Nov 2025–15 Feb 2026

## Scope

- Broker data: local MT5 `GOLD.i#`
- Period: 2025-11-01 through 2026-02-15
- Starting balance: USD 100
- Signal engine: frozen REVISED 0.6 BUY generator
- Scenario A: 0.20 lot, normal engine stop
- Scenario B: 0.02 lot, normal engine stop
- Scenario C: 0.02 lot, execution stop distance widened to 2×
- Scenario D: 0.02 lot, execution stop 2× and target distance 2.5×

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

With the stop at 2× and target distance at 2.5×, 63 non-overlapping trades
remain: 28 targets, 35 stops, no ambiguous outcomes, and 24 signals skipped
while the earlier position remains open. The replay totals `+32.708504R` with
`+0.519183R` expectancy per completed trade.

## Cash result

| Metric | 0.20 normal | 0.02 normal | 0.02 stop 2× | 0.02 stop 2× / target 2.5× |
|---|---:|---:|---:|---:|
| Completed trades | 1 / 87 | 87 / 87 | 84 / 84 | 63 / 63 |
| Ending balance | $16.20 | $215.40 | $357.78 | $591.87 |
| Net profit | -$83.80 | +$115.40 | +$257.78 | +$491.87 |
| Max drawdown | $83.80 | $58.78 | $77.22 | $87.68 |
| Max drawdown / peak | 83.80% | 43.39% | 54.02% | 46.72% |
| Maximum margin | $81.01 | $10.77 | $10.77 | $10.77 |
| Minimum margin level | below stop-out | 813.74% | 697.06% | 697.06% |
| Profit factor | 0.00 | 1.36 | 1.66 | 2.26 |
| Failure | stop-out | none | none | none |

## Target-distance sweep with stop 2×

The target multiplier is measured from entry to the engine's original target;
it is not a fixed reward/risk ratio. Each candidate is replayed independently,
including its effect on overlapping signals.

| Target distance | Trades | TP / SL | Skipped | Expectancy | Ending balance | Profit factor | Max DD / peak |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.25× | 78 | 45 / 33 | 9 | +0.294R | $435.43 | 1.88 | 45.18% |
| 1.50× | 72 | 38 / 34 | 15 | +0.279R | $422.14 | 1.85 | 55.24% |
| 1.75× | 70 | 36 / 34 | 17 | +0.356R | $479.94 | 1.99 | 48.17% |
| 2.00× | 67 | 35 / 32 | 20 | +0.512R | $605.36 | 2.39 | 44.19% |
| 2.15× | 67 | 34 / 33 | 20 | +0.528R | $618.64 | 2.38 | 53.63% |
| 2.25× | 67 | 33 / 34 | 20 | +0.522R | $645.87 | 2.44 | 51.09% |
| 2.50× | 63 | 28 / 35 | 24 | +0.519R | $591.87 | 2.26 | 46.72% |
| 3.00× | 60 | 25 / 35 | 27 | +0.644R | $616.42 | 2.26 | 68.98% |

The 0.20 scenario completes its first trade at a loss, leaving $83.80. The
next trade, opened 2025-11-10 03:35 server time, reaches adverse equity below
the broker's 20% stop-out threshold. The simulated residual balance is $16.20.

## Verdict

For this period, the promising plateau is a 2× stop with a target distance in
the 2.0×–2.25× range. The 2.25× candidate has the highest ending balance and
profit factor, while 2.0× has the lowest peak-relative drawdown in that plateau
and retains the same 67 completed trades. Therefore 2.0× is the more
conservative candidate and 2.25× the performance candidate. The 3× result is
not preferred despite higher R expectancy because it skips 27 signals and its
peak-relative drawdown rises to 68.98%.

These are execution overlays for research, not a new engine default. Selecting
2.25× from the same date range used to compare it creates optimization bias, so
it must pass a later untouched/forward period before adoption.

Calculations use MT5 broker margin/profit functions. Commission, swap,
slippage, and replay-OHLC versus executable bid/ask differences are not
included. No order was sent.
