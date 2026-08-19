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

## Standalone confluence experiments

The original baseline remains available. Three explicit candidates were added
behind CLI flags; none changes the default engine.

### confluence-v1

Implemented independently inside `goldm_bear`:

- Fibonacci 38.2%–61.8% pullback zone from a confirmed bearish impulse;
- M15 supply origin followed by bearish displacement;
- RSI7 pullback and turn-down confirmation;
- Stochastic 14/3 pullback and turn-down confirmation;
- closed-candle bearish momentum restart;
- exhaustion veto from shrinking body/range and oversold oscillators;
- at least three of five votes, with momentum and Fibonacci/supply structure
  mandatory;
- maximum regime displacement of 4 ATR.

### confluence-v2

Because v1 remained weak, v2 independently reimplemented only the relevant
REVISED concept: distinct resistance touches separated by retreat, repeated
rejections, and acceptance cancellation. Strong failed-breakout momentum can
bypass the repeated-touch requirement. There is no import or shared state with
REVISED.

### confluence-v3

V2 did not improve results. V3 therefore returns to v1 and adds an independently
implemented higher-timeframe regime gate: completed H1 bars must close below a
falling H1 SMA20. It does not include the failed repeated-touch gate.

| Window | Baseline + exit | Confluence v1 | Confluence v2 | Confluence v3 |
|---|---:|---:|---:|---:|
| Jan 2025–now | +6.81R | **+12.38R** | +4.16R | +8.40R |
| Nov 2025–15 Feb 2026 | -10.62R | -5.20R | -6.13R | **-3.61R** |
| Jun 2026–now | +6.42R | +3.34R | +1.63R | **+4.58R** |
| Full suite | -126.68R | -52.54R | -55.98R | **-10.32R** |
| Full-suite expectancy | -0.059R | -0.053R | -0.076R | **-0.024R** |
| Full-suite max DD | 144.13R | 69.75R | 66.73R | **24.44R** |

V3 is the strongest single-entry-timeframe result, but it remains negative in
the full suite and the November–February window. No post-hoc time/score filter
is added for that losing window; the next experiment instead changes the
causal timeframe architecture.

## Multi-timeframe confluence-v4

V4 is a separate state machine added only to `goldm_bear`:

```text
closed H1 trend → M15 confluence setup → M5 ARMED → M1 retest entry
```

- Native closed H1 bars require close below a falling SMA20.
- M15 confluence-v1 produces a WATCH setup; it does not enter.
- The three closed M5 bars composing the M15 rejection may validate the setup.
- M15 rejection counts as the first structural touch; M5 must confirm bearish
  momentum without two-close acceptance above resistance.
- A strong M5 failed breakout may arm immediately.
- After ARMED, M1 has 20 closed bars to retest the M15/M5 zone.
- M1 requires a strong rejection or two ordinary touches, micro-break below the
  previous low, bearish close location, and RSI/Stochastic turn-down.
- A strong first M1 continuation may use the already-closed pre-ARM M1 candle
  as its micro-break reference; ordinary rejection still needs two M1 touches.
- Entry is a SELL-stop one tick below the broken M1 low, not the later candle
  close. This preserves causal entry room without moving TP through support.
- Stop is above M5/resistance structure with spread/ATR buffer.
- Target remains in front of the M15 support/psychological barrier.
- TP/SL outcome is tracked on M1; same-bar ambiguity remains conservative.

| Window | M15 setups | H1 rejected | M5 armed | M1 entries | Total R | Expectancy | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jan 2025–now | 257 | 142 | 105 | 72 | +22.09R | +0.307R | 4.72R |
| Nov 2025–15 Feb 2026 | 59 | 33 | 24 | 16 | +3.21R | +0.201R | 4.72R |
| Jun 2026–now | 37 | 15 | 20 | 14 | +5.10R | +0.364R | 3.00R |
| Full suite | 1,027 | 576 | 419 | 303 | **+62.06R** | **+0.205R** | 17.75R |

### 4–19 August SELL evidence

V4 produces three entries, all targets, for `+1.90R` with zero closed-trade
drawdown. The supplied 18 August setup is reconciled as follows:

- M15 setup: 17:00 server time;
- H1 bearish context: valid;
- M5: ARMED at 17:15 after two touches/two rejections;
- M1 micro-break SELL-stop entry: 4393.39 at 17:18;
- structural stop: 4399.50;
- psychological-support target: 4390.50;
- outcome: TARGET, +0.473R.

V4 is the first bear candidate to finish the evidence window, every segmented
stress window, and the full suite above zero. It is retained as the best
research architecture. It is not yet a forward/deployment candidate because
full-suite drawdown is 17.75R, two segmented windows marginally exceed the 4R
gate, and executable spread/slippage stress has not been completed.

## Decision

The existing `goldm_bear` engine and confluence v1–v3 fail the complete
segmented-window promotion test. V4 is positive across all tested windows but
has not passed the drawdown/execution-stress promotion gate. No hour-of-day,
score, or reason filter is selected post hoc. The engine remains research-only;
no Scheduled Task, Telegram sender, order function, or production integration
is created.

The separate REVISED candidate remains frozen at stop multiplier 1.75, target
multiplier 2.5, fixed lot 0.20, reference balance USD 100,000, and no
compounding. No parameter or state is shared with bear.
