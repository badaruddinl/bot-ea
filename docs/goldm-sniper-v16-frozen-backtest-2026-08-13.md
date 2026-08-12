# GoldM Sniper v1.6 — frozen two-year segmented backtest

Date: 2026-08-13
Symbol: `GOLD.i#`
Tester: MT5 real ticks, host timeframe M15, signal-only
Frozen evaluation interval: `2024-02-28` through `2026-02-28`
Quarantined interval not tested: `2026-02-28` through `2026-07-01`

## Frozen artifacts

No EA logic or preset parameter was changed between segments.

| Artifact | SHA-256 before and after all segments |
|---|---|
| `GoldMSniperParity.mq5` | `e652b6454319639c4a9b53e02cbdc7224f6fbe45d7cce66ed0c74b08ad6274e8` |
| `GoldMSniperParity_GOLD_i.set` | `7fd6558909f05afeaf1e7a239f04a10d2a886caaae384bc7891d993a97eb05b5` |

MetaEditor compilation remained clean: `0 errors, 0 warnings`.

## Segment results

| Part | Interval | Signals | BUY/SELL | P1 | P2 | P3 | Total R | Expectancy |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2024-02-28 – 2024-06-28 | 106 | 93/13 | 56.60% | 11.32% | 0.94% | +28.20228R | +0.26606R |
| 2 | 2024-06-28 – 2024-10-28 | 103 | 103/0 | 44.66% | 3.88% | 0.00% | -12.89751R | -0.12522R |
| 3 | 2024-10-28 – 2025-02-28 | 146 | 102/44 | 47.26% | 4.79% | 2.05% | -3.50751R | -0.02402R |
| 4 | 2025-02-28 – 2025-06-28 | 127 | 127/0 | 52.76% | 3.94% | 0.00% | +16.65721R | +0.13116R |
| 5 | 2025-06-28 – 2025-10-28 | 140 | 126/14 | 45.00% | 1.43% | 0.71% | -20.57602R | -0.14697R |
| 6 | 2025-10-28 – 2026-02-28 | 164 | 164/0 | 45.12% | 3.66% | 0.00% | -17.10701R | -0.10431R |

## Aggregate

- Signals: `786`
- Positive segments: `2/6`
- Total: `-9.22856R`
- Weighted expectancy: `-0.01174R` per signal
- P1/P2/P3: `48.22% / 4.58% / 0.64%`
- Direction distribution: `715 BUY / 71 SELL`

The aggregate is close to breakeven but negative. More importantly, performance is
not stable across regimes: four of six independent time segments are negative and
91% of signals are BUY. The positive aggregate contribution is concentrated in two
segments instead of being broadly repeated.

## Promotion decision

The frozen strategy did not meet the strength requirement for a continuous full
two-year run or an OOS test. Therefore:

- no continuous full-period run was launched;
- the quarantined `2026-02-28` to `2026-07-01` interval remains untouched;
- no OOS result was exposed or used for parameter tuning;
- the strategy remains research-only and signal-only.

This preserves the protected interval for a genuinely final OOS evaluation after a
future, independently justified algorithm version passes segmented development
tests.
