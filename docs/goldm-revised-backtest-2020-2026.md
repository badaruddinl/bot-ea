# GOLDM_REVISED 0.6.0 — full 2020–2026 broker backtest

## Scope and provenance

- Symbol: broker `GOLD.i#`
- Requested server-time range: 2020-01-01 through 2026-08-18
- Engine: evidence-tweaked `GOLDM_REVISED` 0.6.0 BUY generator
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

- signals/resolved: 8,273 / 8,273;
- BUY: 8,273;
- SELL: 0;
- core BUY: 6,792;
- SCALPER: 1,481;
- targets: 3,446;
- stops: 4,356;
- ambiguous same-bar outcomes: 471;
- total: `-203.439882R`;
- expectancy: `-0.024591R` per entry;
- maximum drawdown: `405.646836R`;
- fallback promotions: 0;
- duplicate-trigger promotions: 0.

## Annual breakdown

| Year | Signals | TP | SL | Ambiguous | Total R | Expectancy R | Max DD R |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 1,232 | 513 | 650 | 69 | -50.540465 | -0.041023 | 84.470931 |
| 2021 | 1,242 | 541 | 635 | 66 | -69.176331 | -0.055698 | 75.284305 |
| 2022 | 1,275 | 521 | 671 | 83 | -151.706178 | -0.118985 | 163.380017 |
| 2023 | 1,204 | 515 | 606 | 83 | -82.152426 | -0.068233 | 98.720234 |
| 2024 | 1,317 | 556 | 689 | 72 | +8.685818 | +0.006595 | 34.246997 |
| 2025 | 1,347 | 543 | 739 | 65 | +106.489047 | +0.079056 | 42.800398 |
| 2026 | 656 | 257 | 366 | 33 | +34.960652 | +0.053294 | 35.633423 |

## Room breakdown

| Room | Signals | TP | SL | Ambiguous | Total R | Expectancy R |
|---|---:|---:|---:|---:|---:|---:|
| `<1R` | 1,421 | 1,078 | 332 | 11 | -29.529416 | -0.020781 |
| `>=1R` | 6,852 | 2,368 | 4,024 | 460 | -173.910466 | -0.025381 |

## Five-evidence reconciliation

- E1: no confirmation; BUY remains WATCH inside H1 supply.
- E2: BUY CORE confirmed against the nearest M5 supply boundary; target reached
  for about `+1.67R`.
- E3: no confirmation; BUY remains WATCH inside H1 supply.
- E4: the complete SCALPER gate is not met, so no tag or confirmation is
  forced.
- E5: BUY remains WATCH inside active M5 supply; no unsafe confirmation.

## Verdict

FAIL, but materially better than 0.5.0. Signals fall from 24,991 to 8,273,
total loss improves from `-1052.35R` to `-203.44R`, and drawdown falls from
`1238.82R` to `405.65R`. Results remain negative in 2020–2023, while
2024–2026 are positive.

Neither simply removing SCALPER nor applying a post-generation BUY filter is
supported by this evidence: both the `<1R` and `>=1R` groups remain negative.
The improvement comes from changing how BUY setups are formed around nearest
resistance, psychology, and supply/demand context.

Shadow/forward deployment remains disabled. The next revision must be trained
only on pre-2025 data and validated out-of-sample on 2025–2026; parameters
must not be tuned directly against the full-period result.
