# GoldM Sniper v1.6 — session, news, and regime analysis

Date: 2026-08-13
Dataset: the same 786 frozen signals from six segmented MT5 real-tick tests
Interval: `2024-02-28` through `2026-02-28`
Algorithm and preset: unchanged
Protected interval `2026-02-28` through `2026-07-01`: not opened

## Time basis

XM states that its MT4/MT5 servers use GMT+2 in winter and GMT+3 in summer. The
following broad server-time buckets were therefore used as liquidity-regime proxies:

| Bucket | XM server time |
|---|---|
| Asia | 01:00–09:59 |
| London | 10:00–14:59 |
| London–New York overlap | 15:00–18:59 |
| New York late | 19:00–23:58 |

The buckets are intentionally broad because US and European daylight-saving
transition dates are not identical.

## Primary result: time of day dominates the current technical score

| Session | Signals | Total R | Expectancy | Approx. 95% CI |
|---|---:|---:|---:|---:|
| Asia | 259 | -1.591R | -0.0061R | -0.1438 to +0.1315 |
| London | 203 | -38.775R | -0.1910R | -0.3337 to -0.0483 |
| London–New York overlap | 134 | +37.563R | +0.2803R | +0.0785 to +0.4821 |
| New York late | 190 | -6.426R | -0.0338R | -0.1855 to +0.1179 |

The overlap was positive in five of six independent segments. London was negative
in five of six; its one positive segment was only `+0.401R`. Unlike the overall
expectancy confidence interval, both London and overlap intervals exclude zero in
opposite directions. This is the clearest stable relationship in the dataset.

### Overlap by segment

| Part | Signals | Total R | Expectancy |
|---:|---:|---:|---:|
| 1 | 28 | +16.127R | +0.5760R |
| 2 | 20 | -1.562R | -0.0781R |
| 3 | 18 | +6.886R | +0.3825R |
| 4 | 22 | +8.484R | +0.3856R |
| 5 | 20 | +3.321R | +0.1661R |
| 6 | 26 | +4.309R | +0.1657R |

The strongest server hours were 17:00 (`+21.473R`, `+0.5113R/trade`) and 18:00
(`+16.978R`, `+0.2927R/trade`). The weakest cluster was 10:00–14:59, particularly
11:00, 13:00, and 14:00.

## Weekday interaction

| Day | Signals | Total R | Expectancy |
|---|---:|---:|---:|
| Monday | 173 | +1.678R | +0.0097R |
| Tuesday | 149 | -5.898R | -0.0396R |
| Wednesday | 156 | -4.056R | -0.0260R |
| Thursday | 164 | +19.300R | +0.1177R |
| Friday | 144 | -20.253R | -0.1406R |

Session is more informative than weekday alone. Friday overlap remained positive
at `+5.57R`, while Friday London was `-15.07R` and Friday New York late was
`-8.28R`. Thursday overlap was the best day/session combination: 28 signals,
`+17.43R`, or `+0.623R/trade`.

## News correlation

The audit used official dates for US Employment Situation (NFP), CPI, and FOMC
decisions. BLS schedules those major labor/inflation releases primarily at 08:30
Eastern. The Federal Reserve releases its scheduled policy statement at 14:00
Eastern. With XM server time, those normally map near 15:30 and 21:00 respectively.

Only one signal opened in the defined CPI/NFP release window and only one in the
FOMC decision window. Therefore the sample does **not** support the claim that most
losses came from opening exactly on a news print.

| Day type | Signals | Total R | Expectancy |
|---|---:|---:|---:|
| Normal day | 698 | -2.070R | -0.0030R |
| CPI/NFP day | 65 | -10.829R | -0.1666R |
| FOMC day | 23 | +3.670R | +0.1596R |

The timing within CPI/NFP days is more revealing:

| CPI/NFP timing | Signals | Total R | Expectancy |
|---|---:|---:|---:|
| Before server 15:00 | 43 | -14.055R | about -0.327R |
| From server 15:00 onward | 22 | +3.225R | +0.1466R |

NFP days were not materially worse than ordinary Fridays (`-0.1654R` versus
`-0.1422R/trade`). This means a large part of the apparent NFP penalty is actually
the existing Friday/session weakness. CPI and NFP pre-release trading is consistent
with a false-break/consolidation hypothesis, but that is an inference, not proof of
causality. FOMC days were positive, so a blanket “no-news day” rule would remove
profitable observations as well as losses.

## Indicator and scoring diagnostics

### More votes did not mean better probability

| M5 votes | Signals | Total R | Expectancy |
|---:|---:|---:|---:|
| 2 | 387 | -7.351R | -0.0190R |
| 3 | 347 | +7.236R | +0.0209R |
| 4 | 47 | -5.360R | -0.1140R |
| 5 | 5 | -3.755R | -0.7510R |

### High score was inversely related to performance

| Score | Signals | Total R | Expectancy |
|---|---:|---:|---:|
| 70–84 | 137 | +5.953R | +0.0435R |
| 85–89 | 251 | +8.922R | +0.0355R |
| 90–94 | 223 | +3.945R | +0.0177R |
| 95–100 | 175 | -28.049R | -0.1603R |

The current score is therefore a confluence counter, not confidence. Extra
conditions are correlated with each other and can describe an exhausted move rather
than independent confirmation.

### Fibonacci did not add edge in this sample

| Final entry | Signals | Total R | Expectancy |
|---|---:|---:|---:|
| Fibonacci not aligned | 701 | +4.814R | +0.0069R |
| Fibonacci aligned | 85 | -14.043R | -0.1652R |

Fibonacci alignment should not currently be called a probability improvement. It
may be selecting deep retracements or late, crowded confluence. That mechanism must
be tested separately before it receives positive scoring weight.

## Execution-path diagnosis

Trades resolved in under 15 minutes produced `-87.407R` across 206 signals. Trades
lasting 15–59 minutes produced `+25.074R`; 1–3 hours produced `+37.856R`. Duration
is only known after entry, so it cannot be used as a legitimate entry filter. It is
evidence that many accepted setups are being invalidated by immediate liquidity
noise or false breaks.

The short-failure problem occurred in every session, but was least severe in the
overlap. Stops under `0.55 ATR(M15)` had a much larger fast-stop share than stops of
at least `0.75 ATR(M15)`, although simply widening every stop did not create positive
expectancy. The missing variable is more likely regime/timing quality than stop
width alone.

## Regime diagnosis

- `715/786` signals were BUY. The two-of-three D1/H4/H1 continuation context is
  heavily exposed to the long gold trend and does not balance direction across
  regimes.
- SELL signals were modestly positive (`+5.047R`, `+0.0711R/trade`), while BUY was
  negative (`-14.276R`, `-0.0200R/trade`). The SELL sample is only 71 signals, so
  this is directional imbalance evidence, not proof that SELL is intrinsically
  superior.
- London behavior is consistent with the strategy mistaking early-session liquidity
  sweeps for M15 continuation. Confirmation improves after US participation enters.
- The current almost-all-day trading window ignores this empirically large regime
  difference.

## What should be tested next (without touching OOS)

These are hypotheses for a new development version, not changes applied to v1.6:

1. Treat session/regime as a first-class feature. Test overlap-only and London
   suppression on fresh segmented research data, not on the protected interval.
2. For CPI/NFP days, test suppressing pre-15:00 entries and allowing evaluation only
   after a closed post-release M15 bar. Do not use a blanket news-day ban.
3. Remove the interpretation of score as confidence. Re-estimate weights using
   non-overlapping features and report calibrated probabilities separately.
4. Test Fibonacci alignment as neutral metadata or an exhaustion warning rather
   than an automatic positive vote.
5. Diagnose immediate-stop candidates using information available before entry:
   spread/ATR, M15 displacement age, retest depth, distance to session open, and
   distance/time to scheduled news. Do not filter by realized duration.

No full backtest, OOS run, or protected-period access is justified yet. These
relationships must first reproduce in new segmented development windows.

## Source references

- XM server-time FAQ: https://www.xm.com/tr/help-center/trading-platforms/faq-can-i-change-the-time-zone-on-my-trading-terminal
- BLS 2024 release schedule: https://www.bls.gov/schedule/2024/home.htm
- BLS 2025 release schedule: https://www.bls.gov/schedule/2025/home.htm
- BLS 2026 release schedule: https://www.bls.gov/schedule/2026/home.htm
- Federal Reserve FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Federal Reserve statement timing: https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm
