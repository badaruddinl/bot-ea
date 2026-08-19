# goldm_bear — broker M15 backtest 2020–2026

## Scope

- Standalone package: `goldm_bear`
- Symbol/timeframe: local MT5 `GOLD.i#`, M15
- Full-suite window: 2020-01-01 through 2026-08-19 12:00, GMT+3
- Loaded bars: 158,429, including warm-up from 2019-12-02
- Side: SELL only
- No import, parameter, database, or runtime state from `GOLDM_REVISED` or
  production `goldm_signal`
- Same-bar TP/SL is a conservative `-1R`
- Only one replay position can be active; later SELL signals are skipped until
  it closes

The scanner was changed to evaluate only its required trailing window instead
of copying the complete bar prefix at every M15 step. This is a performance
optimization and does not change the signal rules.

## Existing engine, TP/SL-only replay

| Window | Executed | TP / SL / ambiguous | Total R | Expectancy | Max DD |
|---|---:|---:|---:|---:|---:|
| Jan 2025–now | 573 | 341 / 227 / 5 | +6.13R | +0.011R | 19.30R |
| Nov 2025–15 Feb 2026 | 94 | 52 / 42 / 0 | **-8.29R** | **-0.088R** | 17.23R |
| Jun 2026–now | 94 | 63 / 30 / 1 | +7.10R | +0.076R | 6.24R |
| Full suite | 2,098 | 1,074 / 1,010 / 14 | **-137.51R** | **-0.066R** | 160.43R |

## Existing early-invalidation exit enabled

The engine already contained an exit rule for two closes above structural
resistance or one strong bullish displacement above it. The earlier MT5 scan
never used this rule. The causal replay now checks hard TP/SL first and then
closes at the completed M15 candle's close when structural invalidation is
confirmed.

| Window | Executed | TP / SL / invalidated / ambiguous | Total R | Expectancy | Max DD |
|---|---:|---:|---:|---:|---:|
| Jan 2025–now | 593 | 327 / 142 / 119 / 5 | +6.81R | +0.011R | 20.86R |
| Nov 2025–15 Feb 2026 | 97 | 47 / 22 / 28 / 0 | **-10.62R** | **-0.109R** | 17.72R |
| Jun 2026–now | 94 | 61 / 23 / 9 / 1 | +6.42R | +0.068R | 5.82R |
| Full suite | 2,165 | 999 / 602 / 550 / 14 | **-126.68R** | **-0.059R** | 144.13R |

Early invalidation reduces full-suite loss and drawdown but does not create a
cross-regime edge. It worsens the November–February window.

## Overextension diagnosis

The existing score monotonically rewards larger bearish displacement and caps
at 100. On the full suite, 668 score-100 SELLs lose 46.67R. This supports a
causal hypothesis that the engine sells after momentum is already exhausted.
Evidence fields for normalized regime drop, slope, chase distance, and
resistance kind are now persisted in every replay outcome.

An optional maximum regime-drop gate was tested:

| Maximum regime drop | Full suite | Jan 2025–now | Nov–Feb | Jun–now |
|---:|---:|---:|---:|---:|
| 2 ATR | -1.22R | +9.47R | -2.66R | -0.54R |
| 3 ATR | -62.89R | +16.72R | -3.43R | +2.05R |
| 4 ATR | -67.06R | +30.82R | -5.57R | +4.85R |

The 2-ATR cap nearly reaches full-suite break-even but remains negative in two
segmented windows. No cap passes all windows, so it is retained only as a
diagnostic option and not made the default.

## Decision

The existing `goldm_bear` engine fails the segmented-window and full-suite
promotion test. No hour-of-day, score, or reason filter is selected post hoc.
The engine remains research-only; no Scheduled Task, Telegram sender, order
function, or production integration is created.

The separate REVISED candidate remains frozen at stop multiplier 1.75, target
multiplier 2.5, fixed lot 0.20, reference balance USD 100,000, and no
compounding. No parameter or state is shared with bear.
