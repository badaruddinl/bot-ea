# GOLDM_REVISED — 2020–2026 stop 2× / target 2.5×

## Scope

- Broker data: local MT5 `GOLD.i#`, server `XMGlobal-MT5 5`
- Window: 2020-01-01 00:00 through 2026-08-19 10:45, GMT+3
- Engine: frozen `GOLDM_REVISED` 0.6 BUY generator
- Execution overlay: stop distance 2× and target distance 2.5× from the
  engine's original values
- Fixed execution lot: 0.02
- Starting-balance cash views: USD 50 and USD 100

The overlay is not an exact fixed 1:2.5 reward/risk rule. Each trade retains
the engine's structural stop/target proportions before applying the two
multipliers.

## Baseline

| Metric | Normal engine |
|---|---:|
| Signals | 1,434 |
| TP / SL / ambiguous | 546 / 873 / 15 |
| Total R | +176.443406R |
| Expectancy | +0.123043R |
| Maximum drawdown | 59.478842R |

## Corrected execution overlay

The overlay audit now persists both the original engine target and the scaled
execution target. It rejects a scaled BUY target at or below entry and
recomputes overlay drawdown and first-obstacle metrics rather than inheriting
them from the baseline report.

| Metric | Stop 2× / target 2.5× |
|---|---:|
| Executed trades | 919 |
| TP / SL / ambiguous | 328 / 591 / 0 |
| Win rate | 35.69% |
| Skipped while another position was open | 509 |
| Rejected invalid targets | 6 |
| Total R | +166.436267R |
| Expectancy | +0.181106R |
| Maximum drawdown | 26.542675R |
| Execution first-obstacle room below 1R | 460 |
| Targets beyond first obstacle | 909 |
| Targets below 1R | 55 |

Target R is variable: minimum 0.126R, median 2.284R, mean 2.776R, and maximum
13.068R. Therefore this configuration must not be described as fixed RR 2.5.

## Fixed-lot cash path

| Starting balance | Completed | Ending balance | Net | PF | Max DD / peak | Minimum balance | Minimum adverse equity |
|---:|---:|---:|---:|---:|---:|---:|---:|
| $50 | 919 / 919 | $2,101.78 | +$2,051.78 | 1.41 | 65.76% | $29.49 | $22.56 |
| $100 | 919 / 919 | $2,151.78 | +$2,051.78 | 1.41 | 58.82% | $79.49 | $72.56 |

Both balances survive because profits accumulated during the earlier portion
of the 2020-starting sequence before later drawdowns. This does not contradict
the January-2025-starting replay where USD 50 failed: fixed-lot survivability
is path- and start-date-dependent.

## Forward gate

| Gate | Result |
|---|---|
| Positive expectancy and above baseline | PASS |
| Total R above baseline | **FAIL** — 166.44R versus 176.44R |
| Maximum drawdown at most 4R | **FAIL** — 26.54R |
| No first-obstacle room below 1R | **FAIL** — 460 trades |
| No target beyond first obstacle | **FAIL** — 909 trades |
| No fallback promotion | PASS |
| No invalid execution target | PASS after rejecting six candidates |

## Decision

The configuration is profitable but does not qualify for the official forward
test. It is retained only as a research result. No forward scheduled task is
registered, production is unchanged, and the conditional `goldm_bear` phase is
not started.

Cash calculations use MT5 `order_calc_margin` and `order_calc_profit`.
Commission, swap, slippage, and executable bid/ask differences are excluded.
No order was sent.
