# GOLDM_REVISED — segmented windows and full suite

## Terminology and scope

`Partial` in this report means a segmented date window, not partial position
closure. Every trade exits the full fixed 0.02 lot at its stop or target.

Segmented windows:

1. 2025-01-01 through 2026-08-19
2. 2025-11-01 through 2026-02-15
3. 2026-06-01 through 2026-08-19

The `full suite` is 2020-01-01 through 2026-08-19. All timestamps use GMT+3.
The candidates scale the engine's original stop/target distances; they are not
fixed reward/risk ratios.

## Segmented replay results

| Window | Setup | Trades | Total R | Expectancy | Max DD | Room below 1R | Targets beyond obstacle |
|---|---|---:|---:|---:|---:|---:|---:|
| Jan 2025–now | 1.5× : 2.5× | 298 | +96.907R | +0.325R | 16.00R | 14 | 296 |
| Jan 2025–now | 1.75× : 2.5× | 285 | **+121.297R** | **+0.426R** | **9.62R** | 93 | 283 |
| Nov 2025–15 Feb 2026 | 1.5× : 2.5× | 63 | **+36.014R** | **+0.572R** | **8.00R** | 2 | 62 |
| Nov 2025–15 Feb 2026 | 1.75× : 2.5× | 63 | +33.465R | +0.531R | 8.62R | 22 | 62 |
| Jun 2026–now | 1.5× : 2.5× | 18 | **+17.989R** | **+0.999R** | 3.00R | 0 | 18 |
| Jun 2026–now | 1.75× : 2.5× | 18 | +13.991R | +0.777R | 3.00R | 4 | 18 |

Both candidates are R-positive in all three windows. The 1.5× stop performs
better in the two shorter windows, while 1.75× is materially better in the
January-2025-starting window.

## Segmented fixed-lot cash path

| Window | Setup | Start | Completed | Ending balance | PF | Max DD / peak | Result |
|---|---|---:|---:|---:|---:|---:|---|
| Jan 2025–now | 1.5× : 2.5× | $50 | 8 / 298 | $3.47 | 0.00* | 93.06% | insufficient margin |
| Jan 2025–now | 1.5× : 2.5× | $100 | 13 / 298 | $1.09 | 0.00* | 98.91% | stop-out |
| Jan 2025–now | 1.75× : 2.5× | $50 | 11 / 285 | $4.57 | 0.41* | 94.32% | insufficient margin |
| Jan 2025–now | 1.75× : 2.5× | $100 | 285 / 285 | $1,444.46 | 1.81 | 62.27% | completed |
| Nov 2025–15 Feb 2026 | 1.5× : 2.5× | $50 | 14 / 63 | $7.56 | 0.61* | 89.42% | insufficient margin |
| Nov 2025–15 Feb 2026 | 1.5× : 2.5× | $100 | 63 / 63 | $444.48 | 1.94 | 67.32% | completed |
| Nov 2025–15 Feb 2026 | 1.75× : 2.5× | $50 | 13 / 63 | $3.74 | 0.59* | 94.13% | insufficient margin |
| Nov 2025–15 Feb 2026 | 1.75× : 2.5× | $100 | 63 / 63 | $486.18 | 1.96 | 83.87% | completed |
| Jun 2026–now | 1.5× : 2.5× | $50 | 18 / 18 | $161.26 | 2.32 | 34.50% | completed |
| Jun 2026–now | 1.5× : 2.5× | $100 | 18 / 18 | $211.26 | 2.32 | 17.25% | completed |
| Jun 2026–now | 1.75× : 2.5× | $50 | 18 / 18 | $147.17 | 1.99 | 40.26% | completed |
| Jun 2026–now | 1.75× : 2.5× | $100 | 18 / 18 | $197.17 | 1.99 | 20.13% | completed |

`*` Profit factor from a failed, truncated cash path is not comparable with a
completed-window value.

The 1.5× candidate is R-positive for January 2025 but its USD 100 cash path
fails before later winners occur. This is the failure that triggers the 1.75×
candidate. At USD 100, 1.75× is the only candidate that completes all three
segmented windows, although its drawdown remains high.

## Full suite

| Metric | Baseline normal | 1.5× : 2.5× | 1.75× : 2.5× |
|---|---:|---:|---:|
| Trades | 1,434 | 1,004 | 959 |
| Total R | +176.443R | +177.778R | **+180.938R** |
| Expectancy | +0.123R | +0.177R | **+0.189R** |
| Maximum drawdown | 59.479R | 36.698R | **29.502R** |
| First-obstacle room below 1R | 42 | 138 | 336 |
| Targets beyond first obstacle | — | 994 | 949 |
| $50 ending balance | — | $1,478.12 | **$1,967.66** |
| $100 ending balance | — | $1,528.12 | **$2,017.66** |
| Cash PF | — | 1.31 | **1.40** |

Both full-suite cash paths survive because profits from the early years build a
buffer before the losing sequences seen in later segmented starts. Full-suite
survival therefore does not make USD 50 safe.

## Decision

The 1.75× : 2.5× candidate is more robust than 1.5× : 2.5×: it is the only one
of those two that completes all segmented USD 100 cash paths. The earlier
2× : 2.5× candidate must, however, remain in the comparison.

## Comparison with 2× : 2.5×

| Window | Setup | Total R | Expectancy | R DD | $100 ending | PF | Cash DD / peak | Minimum balance |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Jan 2025–now | 1.75× : 2.5× | **+121.30R** | **+0.426R** | 9.62R | $1,444.46 | 1.81 | **62.27%** | **$49.20** |
| Jan 2025–now | 2× : 2.5× | +114.73R | +0.410R | **8.78R** | **$1,522.35** | **1.81** | 73.08% | $35.05 |
| Nov 2025–15 Feb 2026 | 1.75× : 2.5× | **+33.47R** | **+0.531R** | 8.62R | $486.18 | 1.96 | 83.87% | $18.35 |
| Nov 2025–15 Feb 2026 | 2× : 2.5× | +32.71R | +0.519R | **6.00R** | **$591.87** | **2.26** | **46.72%** | **$74.80** |
| Jun 2026–now | 1.75× : 2.5× | **+13.99R** | **+0.777R** | 3.00R | **$197.17** | **1.99** | **20.13%** | **$79.87** |
| Jun 2026–now | 2× : 2.5× | +10.99R | +0.611R | 3.00R | $183.13 | 1.74 | 23.00% | $77.00 |
| Full suite | 1.75× : 2.5× | **+180.94R** | **+0.189R** | 29.50R | $2,017.66 | 1.40 | 59.58% | $72.20 |
| Full suite | 2× : 2.5× | +166.44R | +0.181R | **26.54R** | **$2,151.78** | **1.41** | **58.82%** | **$79.49** |

The 2× stop leads full-suite cash balance, profit factor, and drawdown, and is
clearly stronger in the November–February window. The 1.75× stop leads
full-suite total R and expectancy, preserves more capital in the
January-starting path, and performs better in the June window. The 2× stop also
creates more first-obstacle-room violations (460 versus 336 in the full suite).
Neither candidate dominates across all objectives, so both remain separate
research candidates while 1.5× is dropped from the shortlist.

Neither shortlisted candidate passes the official forward gate. Drawdown
exceeds 4R in two segmented windows and the full suite, first-obstacle
violations remain, and almost every target crosses the first obstacle without
causal acceptance confirmation. No forward task is registered. Production is
unchanged and the conditional `goldm_bear` phase remains unstarted.

Commission, swap, slippage, and executable bid/ask differences are excluded.
No order was sent.
