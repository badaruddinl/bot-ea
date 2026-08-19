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

- signals/resolved: 1,434 / 1,434;
- BUY: 1,434;
- SELL: 0;
- core BUY: 1,384;
- SCALPER: 50;
- targets: 546;
- stops: 873;
- ambiguous same-bar outcomes: 15;
- total: `+176.443406R`;
- expectancy: `+0.123043R` per entry;
- maximum drawdown: `59.478842R`;
- fallback promotions: 0;
- duplicate-trigger promotions: 0.

## Annual breakdown

| Year | Signals | TP | SL | Ambiguous | Total R | Expectancy R | Max DD R |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 234 | 100 | 132 | 2 | +56.93 | +0.24 | 17.13 |
| 2021 | 178 | 76 | 100 | 2 | +36.33 | +0.20 | 14.55 |
| 2022 | 164 | 52 | 111 | 1 | -6.74 | -0.04 | 33.34 |
| 2023 | 192 | 64 | 127 | 1 | -7.08 | -0.04 | 31.36 |
| 2024 | 254 | 88 | 164 | 2 | +5.90 | +0.02 | 37.74 |
| 2025 | 325 | 124 | 195 | 6 | +59.61 | +0.18 | 24.23 |
| 2026 | 87 | 42 | 44 | 1 | +31.49 | +0.36 | 6.84 |

## Profile breakdown

| Profile | Signals | TP | SL | Total R | Expectancy R |
|---|---:|---:|---:|---:|---:|
| CORE | 1,384 | 509 | 860 | +174.54 | +0.13 |
| SCALPER | 50 | 37 | 13 | +1.90 | +0.04 |

## Regime annotation

| Regime | Signals | Total R | Expectancy R | Max DD R |
|---|---:|---:|---:|---:|
| COVID emergency, 30 Jan 2020–5 May 2023 | 621 | +80.10 | +0.13 | 33.34 |
| Post-COVID, 6 May 2023–31 Jan 2026 | 741 | +52.91 | +0.07 | 59.48 |
| Pre-war escalation, 1–27 Feb 2026 | 11 | +8.31 | +0.76 | 1.00 |
| Active-war validation window, 28 Feb–1 Jul 2026 | 23 | +15.50 | +0.67 | 3.00 |
| Post-1 July validation window | 16 | +13.23 | +0.83 | 1.00 |

## Five-evidence reconciliation

- E1: no confirmation; BUY remains WATCH inside H1 supply.
- E2: BUY CORE confirmed against the nearest M5 supply boundary; target reached
  for about `+1.67R`.
- E3: no confirmation; BUY remains WATCH inside H1 supply.
- E4: the complete SCALPER gate is not met, so no tag or confirmation is
  forced.
- E5: BUY remains WATCH inside active M5 supply; no unsafe confirmation.

## Verdict

PASS as a research candidate, not as shadow deployment approval. Signals fall
from 24,991 to 1,434, total improves from `-1052.35R` to `+176.44R`, and
drawdown falls from `1238.82R` to `59.48R`. Years 2022 and 2023 remain mildly
negative, so forward deployment is still not automatic.

The improvement does not come from `buy_only=true` or a post-generation side
filter. REVISED forms BUY hypotheses only, while bearish setups act as
negative evidence that invalidates BUY. Entry formation requires either no
active supply or a causally observable H1-supply breakout regime: above H1
SMA20, positive-but-moderate H1 trend (`0–2 ATR`), and H1 efficiency below
`0.20`.

## External regime validation

- WHO dates the COVID-19 PHEIC from 30 January 2020, characterized the outbreak
  as a pandemic on 11 March 2020, and ended the PHEIC on 5 May 2023:
  https://www.who.int/europe/emergencies/situations/covid-19
- U.S. CENTCOM states that Operation Epic Fury commenced on 28 February 2026,
  so 1–27 February is treated as pre-war escalation rather than active war:
  https://media.defense.gov/2026/Mar/29/2003904283/-1/-1/1/OPERATION-EPIC-FURY-FACT-SHEET-THE-FIRST-29-DAYS.PDF
- The 2026 Economics Letters event study reports weak gold safe-haven behavior
  and higher volatility around the Iran escalation:
  https://doi.org/10.1016/j.econlet.2026.113010

These dates annotate evaluation only. They are not hardcoded entry filters.

Shadow/forward deployment remains disabled. The next revision must be trained
only on pre-2025 data and validated out-of-sample on 2025–2026; parameters
must not be tuned directly against the full-period result.
