# GOLDM production baseline research — 2026-08-18

## Scope and evidence classification

- Production baseline: `4789a10b8b665f5611809edbed3e4ef66a0da557`.
- EA and production input contract in `main` were verified unchanged from that
  baseline before the tests.
- Symbol: `GOLD.i#`; broker-server summer offset GMT+3.
- Research interval: `[2026-08-04, 2026-08-19)`.
- Statistical classification: `DIAGNOSTIC_ONLY`. The interval has already been
  exposed through live operation and this investigation; it is not blind OOS.
- The separate `goldm_bear` package was not imported, executed, or used to make
  any production-baseline decision in this research.

The evidence sources were the read-only production SQLite outbox, exact
production MQL5 source and inputs, MT5 broker history, and local Strategy Tester
logs. Production worker, EA, Telegram delivery, and AutoTrading settings were
not changed.

## Live-event evidence

For 4–18 August the database contains:

| Event | Count |
| --- | ---: |
| WATCH / early candidate | 20 |
| Promoted | 10 |
| Cancelled WATCH | 10 |
| ENTRY READY signal | 10 |
| Model outcome | 6 |
| Account-binding rejection | 6 |

All ten ENTRY READY signals were BUY; no production SELL was recorded. The six
resolved outcomes were three STOP, two PROTECTED_STOP, and one M1_MANAGEMENT,
for total `-1.2650R` and average `-0.21083R`.

## Exact-production backtests

The tester compiled with zero errors and zero warnings. The EA is signal-only,
so the report balance remains USD 100; the meaningful result is the EA's
`SNIPER_PERFORMANCE`/`OnTester` R metric.

| Diagnostic interval | Signals | BUY / SELL | P(hit 1R) | Total R | Expectancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4–11 Aug | 14 | 12 / 2 | 42.86% | -2.02502R | -0.14464R |
| 12–16 Aug | 6 | 6 / 0 | 50.00% | +0.29426R | +0.04904R |
| 17–18 Aug | 2 | 2 / 0 | 50.00% | -0.75212R | -0.37606R |
| 4–18 Aug combined | 22 | 20 / 2 | 45.45% | -2.48289R | -0.11286R |

The combined run produced 17 M1 fallback attempts for 22 final signals. The
first week produced eight fallbacks for fourteen signals; the 12–16 August
segment produced six for six. Fallback attempts can be rejected later, so the
counter is not exactly the number of fallback signals, but it proves fallback
is a dominant path rather than an exceptional recovery path.

## Delayed-fallback M1 ablation

A separate tester `.set` changed only `InpMaximumM1EntryBars` from 5 to 96 and
the research run id. This delays fallback and gives refined M1 much longer to
appear; it does not fully disable fallback.

| Interval | Signals | BUY / SELL | Fallback attempts | Total R | Expectancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4–18 Aug exact production | 22 | 20 / 2 | 17 | -2.48289R | -0.11286R |
| 4–18 Aug delayed fallback | 22 | 20 / 2 | 4 | -0.63778R | -0.02899R |
| 17–18 Aug exact production | 2 | 2 / 0 | 3 | -0.75212R | -0.37606R |
| 17–18 Aug delayed fallback | 2 | 2 / 0 | 2 | -0.75212R | -0.37606R |

Longer M1 refinement materially improved the two-week aggregate but did not
repair the latest period and did not reduce BUY dominance. Therefore M1 timing
matters, but it is not the sole defect.

## Six recent resolved production signals

`roomR` is the distance from entry to the nearest confirmed swing resistance or
psychological resistance, divided by initial risk. It is an obstacle metric,
not the farther objective selected by `NearestObjectiveTarget()`.

| Setup (server) | Result | M1 confirmed | Pattern | M5 votes | roomR |
| --- | ---: | --- | --- | ---: | ---: |
| 17 Aug 15:45 | +0.2479R | yes | BULL_MICRO_BREAK | 2 | 0.22 |
| 17 Aug 18:00 / 22:34 WIB promote | -1.0000R | **no** | BULL_REJECTION | 3 | 1.01 |
| 18 Aug 02:15 / around 07:00 WIB | +0.2184R | yes | **BULL_ENGULFING** | 3 | 1.19 |
| 18 Aug 03:15 / around 08:00 WIB | -1.0000R | yes | BULL_MICRO_BREAK | 3 | 1.31 |
| 18 Aug 09:15 / around 14:00 WIB | -1.0000R | yes | BULL_REJECTION | 3 | **0.28** |
| 18 Aug 12:45 / around 17:30 WIB | +1.2687R | yes | BULL_REJECTION | 2 | **1.66** |

The one non-M1-confirmed signal lost `-1R`. Requiring M1 confirmation would
remove that loss, but the remaining five M1-confirmed observations still total
`-0.2650R`. M1 confirmation alone is therefore insufficient.

Confidence is also not calibrated as probability: confidence/score 92 and 96
lost, while score 83 returned +1.2687R. A high score cannot override missing M1
confirmation or insufficient room.

## Root causes in source

### 1. First obstacle is discarded

`NearestObjectiveTarget()` supplies candidates to `AddTargetCandidate()`, but a
candidate is retained only when it already satisfies `InpMinimumProjectedR`.
For BUY, a nearby resistance can therefore disappear from the room check while
a farther weekly/daily/Fibonacci target survives. This explains the 0.28R room
at the 09:15 setup and the target beyond the 4440 psychological barrier at the
03:15 setup.

This is inconsistent with empirical evidence that support/resistance levels
predict intraday interruptions, and that take-profit/stop orders cluster around
round numbers: [FRBNY *Support for Resistance*](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf) and
[FRBNY Staff Report 125](https://www.newyorkfed.org/research/staff_reports/sr125.html).

### 2. M1 micro-break is optional

The refined entry requires `heldInvalidation` and any two of:

1. directional M1 candle;
2. M1 close through the preceding high/low (`microBreak`);
3. RSI on the directional side of 50.

Thus RSI plus candle color can pass without an actual micro-break, or candle
color plus a marginal micro-break can pass while RSI disagrees.

### 3. Fallback bypasses refined M1

At the M1 bar limit, a setup may enter when invalidation held and either M5 has
three votes or Fibonacci aligns. The 17 August 22:34 WIB confidence-92 promote
used `m1Confirmed=false` and lost. Fallback must not share the same promotion
status as genuinely refined M1.

### 4. Early management is not structural

After 1R, two adverse M1 bars—or one after 2R/Fibonacci reaction—close the model
without checking whether the original M15 resistance target remains structurally
valid. The 12:45 setup exited at +1.2687R with MFE 1.5565R; the original target
was not counterfactually tracked after closure. This is why the current evidence
cannot distinguish prudent protection from a premature close without a shadow
tracker.

## Candidate production-baseline rule for the next experiment

This is a research candidate, not a production change:

1. Calculate the nearest directional obstacle before target selection.
2. If `firstObstacleR < 1.0`, reject promotion regardless of confidence.
3. If `1.0 <= firstObstacleR < 1.5`:
   - require real M1 confirmation; fallback forbidden;
   - require `microBreak=true` and all three M1 votes;
   - require a strong M5 pattern such as engulfing/star, not a bare micro-break;
   - cap TP slightly before the obstacle.
4. If `firstObstacleR >= 1.5`, keep the normal target search but still require
   real M1 confirmation.
5. Cap confidence below promotion threshold whenever the room gate fails.
6. After a model exit, shadow-track the original stop, target, first obstacle,
   MFE, and MAE for the remaining horizon.

On the six exposed outcomes this rule would reject the fallback loss, the 0.28R
room loss, the weak-pattern 1.31R loss, and one small protected winner; it would
retain the engulfing +0.2184R and the 1.66R-room +1.2687R examples. That apparent
improvement is in-sample and must not be treated as expected future performance.

## Next validation gate

Before any production edit:

- implement the candidate as an isolated baseline-research switch, not through
  `goldm_bear`;
- backtest exact production vs room-only, strict-M1-only, and combined variants;
- report BUY and SELL separately;
- require a new blind forward period beginning no earlier than 19 August;
- do not promote solely on confidence score.
