# GoldI independent directional research v1

Run date: 2026-08-17

Target: `GOLD.i#`

Production `ALL`: unchanged, strategy 1.72 D7 baseline

Execution authority: research only; demo and real activation are not authorized

## What was built

This experiment implements genuinely independent BULL and BEAR entry algorithms. It does not obtain directional behavior by filtering BUY or SELL signals from the production `ALL` engine.

Each side has six frozen base candidates across three families:

- trend reclaim;
- liquidity sweep; and
- squeeze expansion.

The plan ranks base candidates on `train`, applies seven pre-registered local risk/holding tweaks to the train winner, selects using `train + validation_1`, and uses `validation_2` for confirmation only. A failed confirmation cannot trigger another tweak against the same confirmation fold.

## Registered inputs

- bar source manifest: `config/goldi-directional-bar-dataset-v1.json`
- folds: `config/goldi-directional-folds-v1.json`
- candidates and tweak budget: `config/goldi-directional-candidates-v1.json`
- runner: `scripts/run-goldi-directional-research.py`

The evaluated half-open range was `[2022-02-28, 2023-03-28)`, wholly inside the authorized Development interval. Warm-up began at `2021-01-01`. The protected quarantine and known-exposure periods were not read.

The source is an immutable EPSOFT archive at commit `d34d6497b2fcf9e2f1b6ea13fd2ed22f4ad708ea`, archive SHA-256 `8c1e92dc97eed9495cb3b4c44903ee8bce0b3ae47dcf85ddcb49f91ee3c210c6`. The parser converts each row's explicit GMT offset to UTC; the source changes between GMT-0500 and GMT-0400 under DST.

## Result after candidate selection and tweaking

| Side | Provisional best | Train | Validation 1 | Confirmation | Decision |
|---|---|---:|---:|---:|---|
| BULL | `BULL_SQUEEZE_EXPANSION_SESSION_A__T05` | 11 trades, +0.324R expectancy, PF 2.50 | 3 trades, +0.323R expectancy, PF 4.61 | 10 trades, +0.051R expectancy, PF 1.18 | rejected: minimum sample gates failed |
| BEAR | `BEAR_SQUEEZE_EXPANSION_SESSION_A__T05` | 3 trades, +0.418R expectancy | 2 trades, -0.489R expectancy, PF 0.16 | 5 trades, -0.250R expectancy, PF 0.48 | rejected: performance and sample gates failed |

Immutable local report SHA-256: `c321846810867f1d6baae863051e3d9033819869187a57a9b4805f23f5f0200b`.

No candidate is promoted. BULL is promising only as a low-sample lead; BEAR is rejected in this form. Neither is added to the production `StrategyEngine` enum or deployed.

## Evidence limitations and next gate

This is an exploratory BID-OHLC bar model. It has no broker-specific ask, spread path, slippage, or `GOLD.i#` real ticks. Same-bar stop/target collisions are conservatively scored as stop-first and a fixed 0.30 quote-unit round-trip cost is deducted.

The next legitimate step is a newly registered, isolated `GOLD.i#` real-tick Development dataset with sufficient unseen rows. It must be used to create a fresh pre-registered candidate/fold plan. The locked legacy validation interval may be opened only once under its existing protocol; it must not be used to rescue or tune these rejected candidates.

The older untracked directional reports are diagnostic only. Their stated fixed GMT-0500 assumption is contradicted by the source rows, and their reported end date extends beyond continuous source coverage.
