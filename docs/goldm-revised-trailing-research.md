# GOLDM_REVISED — causal M1 trailing research

## Scope

- Candidate: REVISED stop multiplier 1.75, target multiplier 2.5
- Trailing is research-only and not connected to runtime
- Trail activation requires a completed M1 close
- The updated stop becomes active on the next M1 bar
- Same-bar stop/target remains conservative
- Fixed-lot cash view: USD 100,000, lot 0.20

## Why trailing was investigated

Of 640 full-suite STOP outcomes without trailing:

| Prior MFE | STOP trades |
|---:|---:|
| at least 0.25R | 478 |
| at least 0.50R | 382 |
| at least 1.00R | 232 |
| at least 1.50R | 138 |
| at least 2.00R | 80 |

These are floating excursions, not realized profit. Aggregate MFE alone cannot
prove a trailing rule because profitable trades may retrace before eventually
reaching target. Every policy was therefore replayed causally on M1.

## Full-suite policy sweep

| Policy | Signals | Total R | Expectancy | R DD | Trail exits |
|---|---:|---:|---:|---:|---:|
| No trail | 959 | +180.94R | **+0.189R** | 29.50R | 0 |
| BE at 0.5R | 1,123 | +164.33R | +0.146R | 30.02R | 520 |
| Lock 0.1R at 0.75R | 1,084 | +163.79R | +0.151R | 27.13R | 406 |
| Lock 0.25R at 1R | 1,069 | +148.69R | +0.139R | 28.84R | 327 |
| Step fast | 1,177 | **+186.30R** | +0.158R | **17.65R** | 596 |
| Step slow | 1,081 | +140.62R | +0.130R | 21.02R | 356 |
| BE at 1.5R | 987 | +165.79R | +0.168R | 30.84R | 165 |
| Lock 0.5R at 2R | 980 | +152.54R | +0.156R | 37.86R | 101 |
| Step late | 1,009 | +144.54R | +0.143R | 31.12R | 192 |

Step fast is the only policy that improves total R and materially lowers R
drawdown. It does so by closing positions sooner and allowing more later base
signals, but expectancy per trade declines.

## Fixed-lot cash comparison

| Policy | Ending balance | Net profit | PF | Cash DD |
|---|---:|---:|---:|---:|
| No trail | **$119,191.80** | **+$19,191.80** | 1.40 | 2.20% |
| Step fast | $113,219.90 | +$13,219.90 | **1.46** | **1.86%** |

Fixed lot makes dollar risk vary with stop distance. Step fast therefore has
higher total R but substantially lower USD profit than no trail.

## Segmented validation: no trail versus step fast

| Window | Policy | Total R | Expectancy | R DD | Net USD | PF | Cash DD |
|---|---|---:|---:|---:|---:|---:|---:|
| 4–19 Aug | No trail | **+11.95R** | **+1.086R** | 1.00R | **+$819.95** | 2.39 | 0.20% |
| 4–19 Aug | Step fast | +7.19R | +0.653R | 1.00R | +$448.27 | **2.45** | **0.14%** |
| Jan 2025–now | No trail | **+121.30R** | **+0.426R** | 9.62R | **+$13,449.00** | 1.81 | 0.88% |
| Jan 2025–now | Step fast | +115.65R | +0.329R | **8.90R** | +$9,816.66 | **2.06** | **0.71%** |
| Nov–Feb | No trail | **+33.47R** | **+0.531R** | 8.62R | **+$3,862.80** | **1.96** | 0.95% |
| Nov–Feb | Step fast | +20.00R | +0.263R | **7.90R** | +$2,386.07 | 1.90 | **0.63%** |
| Jun–now | No trail | **+13.99R** | **+0.777R** | 3.00R | **+$971.95** | 1.99 | 0.23% |
| Jun–now | Step fast | +10.38R | +0.546R | 3.00R | +$678.65 | **2.33** | **0.20%** |

No trail wins total R, expectancy, and USD profit in every segmented window.
Step fast consistently reduces cash drawdown and often improves profit factor,
but the return sacrifice is material.

## Decision

Do not apply fixed trailing to REVISED. Keep the frozen candidate without
trailing when the objective is expectancy and profit. `STEP_FAST` may remain a
separate capital-protection research profile, but it is not a replacement and
is not enabled in shadow/runtime.
