# GOLDM_REVISED 0.5.0 — full 2020–2026 broker backtest

## Scope and provenance

- Symbol: broker `GOLD.i#`
- Requested server-time range: 2020-01-01 through 2026-08-18
- Engine: stable `GOLDM_REVISED` 0.5.0
- Data source: local MT5 connected read-only to `XMGlobal-MT5 5`
- No order API, worker, Telegram polling, or production-terminal restart

The VM production terminal was limited to `maxbars=100000`, with M1 coverage
starting in May 2026. The local terminal was backed up, changed to
`maxbars=10000000`, restarted locally, and allowed to download the broker
archive. Long MT5 requests were chunked and replay histories use rolling
windows so the six-year run does not copy all prior bars on every M1 candle.

## Verified history coverage

| Timeframe | Bars | First bar | Last bar |
|---|---:|---|---|
| M1 | 2,347,991 | 2019-12-30 | 2026-08-19 |
| M5 | 471,024 | 2019-12-23 | 2026-08-19 |
| H1 | 40,070 | 2019-11-04 | 2026-08-19 |
| D1 | 1,839 | 2019-07-05 | 2026-08-19 |

The earlier bars provide causal warmup. The evaluated range remains
2020-01-01 through the exclusive end at 2026-08-19 server time.

## Overall result

- signals/resolved: 24,991 / 24,991;
- BUY: 14,022;
- SELL: 10,969;
- core BUY: 10,429;
- SCALPER: 3,593;
- targets: 10,165;
- stops: 13,487;
- ambiguous same-bar outcomes: 1,339;
- total: `-1052.350100R`;
- expectancy: `-0.042109R` per entry;
- maximum drawdown: `1238.818043R`;
- fallback promotions: 0;
- duplicate-trigger promotions: 0.

## Annual breakdown

| Year | Signals | TP | SL | Ambiguous | Total R | Expectancy R | Max DD R |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 3,669 | 1,476 | 1,964 | 229 | -255.372963 | -0.069603 | 281.941083 |
| 2021 | 3,741 | 1,537 | 1,967 | 237 | -276.493183 | -0.073909 | 282.610175 |
| 2022 | 3,818 | 1,597 | 2,011 | 210 | -251.350508 | -0.065833 | 267.828521 |
| 2023 | 3,782 | 1,593 | 1,938 | 251 | -145.160274 | -0.038382 | 169.528487 |
| 2024 | 3,936 | 1,587 | 2,178 | 171 | -231.472429 | -0.058809 | 245.527877 |
| 2025 | 3,947 | 1,559 | 2,248 | 140 | +78.149611 | +0.019800 | 60.892829 |
| 2026 | 2,098 | 816 | 1,181 | 101 | +29.349647 | +0.013989 | 67.468355 |

## Side breakdown

| Side | Signals | TP | SL | Ambiguous | Total R | Expectancy R |
|---|---:|---:|---:|---:|---:|---:|
| BUY | 14,022 | 6,340 | 7,016 | 666 | -353.232009 | -0.025191 |
| SELL | 10,969 | 3,825 | 6,471 | 673 | -699.118091 | -0.063736 |

## Verdict

FAIL. The five-evidence improvements do not generalize across the broker's
full M1 archive. Results are negative in every year from 2020 through 2024;
2025 and 2026 are only mildly positive. SELL is materially worse than BUY, but
BUY is also negative over the complete period.

Shadow/forward deployment remains disabled. The next revision must be trained
only on pre-2025 data and validated out-of-sample on 2025–2026; parameters
must not be tuned directly against the full-period result.
