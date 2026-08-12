# GoldM Sniper v1.4 Backtest — 2026-08-12

## Decision

**Do not promote this strategy to Telegram A+ or live authority.** The v1.4
deterministic signal contract produced negative expectancy in the research,
validation, and real-tick backtest windows.

This is a signal-only parity test. It never calls `CTrade`, `OrderSend`, or any
other order execution API. Entry, stop, target, and outcomes are simulated from
the tester price stream in R units.

## Timeframe contract

The Strategy Tester host period is M15. The strategy explicitly uses:

```text
D1/H4/H1  market context and trend alignment
M15       key-level breakout and retest setup
M5        closed-bar price-action and momentum confirmation
M1        final micro-break entry refinement and post-1R close management
real tick hard SL / 1R / 2R / 3R barrier ordering
```

M1 cannot create direction or a setup. It may only refine an already valid M15
and M5 candidate. The M1 trigger candle supplies the execution stop reference
with a `0.05 ATR M15` buffer. After +1R, M1 micro-structure may close the signal;
before +1R, only the hard stop or time horizon can end it.

## Deterministic gates

- D1/H4/H1 EMA 50/200 alignment
- previous-day, previous-week, H1 swing, and psychological key levels
- M15 body/range at least 0.60
- breakout displacement between 0.10 and 0.60 ATR M15
- breakout wick no greater than 35%
- relative tick volume at least 0.80
- spread/ATR no greater than 0.10
- retest within 10 closed M15 candles
- M5 rejection, engulfing, or micro-break plus RSI/Stochastic momentum
- M1 directional micro-break within three closed candles
- technical score at least 93
- nearest opposing level must provide at least 3R
- outcome horizon: 96 M15 bars

## Results

The older windows use generated ticks because local real ticks for `GOLD.i#`
begin on `2026-05-01`. The later windows use every tick based on real ticks.

| Evidence layer | Window | Signals | P(1R) | P(2R) | P(3R) | Total R | Expectancy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Research screen, generated | 2025-03-01–2025-09-01 | 8 | 25.0% | 12.5% | 12.5% | -4.000R | **-0.500R** |
| Validation, generated | 2025-09-01–2026-01-01 | 8 | 37.5% | 12.5% | 0.0% | -4.614R | **-0.577R** |
| Backtest, real ticks | 2026-05-01–2026-08-01 | 1 | 0.0% | 0.0% | 0.0% | -1.000R | **-1.000R** |
| Confirmation, real ticks | 2026-08-01–2026-08-12 | 0 | — | — | — | 0.000R | unavailable |

### Research screen

- 8 A+ signals: 8 BUY, 0 SELL
- 7 hard stops, 1 reached +3R
- average MFE: +0.866R
- average MAE: -0.977R
- average projected room: 5.258R
- average score: 94.62
- 37 room candidates: 21 below 2R, 5 at 2.0–2.49R, 1 at 2.5–2.99R,
  and 10 at 3R or greater

### Validation

- 8 A+ signals: 8 BUY, 0 SELL
- 6 hard stops, 2 M1-managed exits
- managed outcomes: +0.192R and +1.194R
- average MFE: +0.844R
- average MAE: -0.875R
- average projected room: 4.897R
- average score: 94.50
- no signal reached +3R

### Real-tick backtest

One A+ signal was produced:

```text
Time        : 2026-07-20 17:15 server time
Side        : SELL
Level       : 4007.10
Entry       : 3998.78
Stop        : 4001.62
Target      : 3990.00
Projected R : 3.092
Score       : 93
Outcome     : -1R after 35 seconds
MFE         : +0.099R
```

The room distribution had four candidates at 3R or greater, but three failed the
technical score gate. The only promoted technical A+ failed immediately.

### Real-tick confirmation

No A+ signal was produced. One candidate had projected room `2.624R`, so it was
correctly retained below the 3R A+ promotion threshold.

## Interpretation

The requested M15 → M5 → M1 structure works technically, but the current entry
edge is not profitable. Tight M1 execution stops create attractive projected R
while making the candidate vulnerable to normal micro-noise. Most losses occur
within minutes and before +1R.

High projected R and a score above 93 are therefore not evidence of high
probability. The current sample also has directional imbalance: the generated
windows produced only BUY signals.

The next research pass should remain in-sample and compare predeclared M1 stop
buffers and acceptance rules. It must not lower the 3R gate or tune against the
already observed real-tick confirmation window. A new future period is required
for untouched OOS evaluation.

## Evidence

Primary agent journal:

```text
C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\logs\20260812.log
```

Generated configs and compile log:

```text
data\backtests\goldm_sniper_signal_v1\configs\
data\backtests\goldm_sniper_signal_v1\compile\GoldMSniperParity.compile.log
```

MetaEditor result: `0 errors, 0 warnings`. As with the legacy harness, MT5 did not
emit command-line HTML reports; the agent journal and tester cache are the
authoritative local evidence.
