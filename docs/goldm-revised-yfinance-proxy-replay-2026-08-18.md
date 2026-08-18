# GOLDM_REVISED Yahoo proxy replay — 4–19 August 2026

## Status

This is an **auxiliary** replay, not the broker-exact acceptance test. It uses
Yahoo Finance `GC=F` because that was explicitly requested for the diagnostic
pass. `GC=F` is COMEX gold futures; it is not `GOLD.i#` and can differ in price,
session boundaries, spread, and candle construction.

The requested end is 19 August 2026 00:00 server time. At execution time the
latest available M1 candle was 18 August 2026 19:36 GMT+3, so this is not a
complete 19 August sample.

## Reproducible command

```powershell
python scripts/research-goldm-revised-yfinance.py `
  --from-server-time 2026-08-04 `
  --to-server-time 2026-08-19 `
  --server-utc-offset-minutes 180 `
  --output-dir runtime_data/goldm_revised_yfinance_20260804_19
```

The research dependencies are isolated in the `research` optional dependency
group. The live and shadow engine dependency path remains unchanged.

## Data coverage

- M1 source: Yahoo Finance `GC=F`, downloaded in end-exclusive chunks of at
  most seven days because Yahoo rejects longer M1 requests.
- Actual M1 coverage: 3 August 2026 01:10 through 18 August 2026 19:36 GMT+3.
- M1 bars: 16,231.
- M5 is resampled from the collected M1 data.
- H1 and D1 are downloaded separately to provide causal obstacle history.
- Fractal support/resistance plotted with a centered rolling window is
  diagnostic only. It is never used for entry decisions because it would use
  future candles.

## Preliminary result

| Metric | Result |
| --- | ---: |
| Signals | 2 |
| BUY / SELL | 2 / 0 |
| Resolved | 2 |
| Targets / stops | 1 / 1 |
| Total R | +0.5445R |
| Expectancy | +0.2722R |
| Maximum drawdown | 1.0000R |
| First-obstacle violations below 1R | 0 |
| Fallback promotions | 0 |
| Duplicate trigger promotions | 0 |

Resolved observations:

| Trigger (GMT+3) | Side | Entry | First obstacle | Result | R |
| --- | --- | ---: | ---: | --- | ---: |
| 7 Aug 02:55 | BUY | 4310.10 | 1.77R | stop | -1.0000R |
| 13 Aug 13:00 | BUY | 4441.40 | 1.59R | target | +1.5445R |

## Interpretation

The obstacle and no-fallback gates behaved as designed on this proxy, but two
resolved trades are far below the required sample size. No REVISED entry was
produced on 17–18 August in the proxy data. Therefore this run cannot reconcile
the five broker samples (22:34, 07:00, 08:00, 14:00, and 17:30 WIB), cannot be
used to tune the frozen configuration, and does not authorize shadow rollout or
production replacement.

The next required result is the same causal replay on broker `GOLD.i#` bars.
That replay must retain the broker timestamps and inspect the five named samples
before any forward test is enabled.
